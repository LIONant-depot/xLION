#pragma once
//
// Linux port (linux-headless branch): the kernel32 objects the headless editor really uses, on POSIX.
// Included at the end of windows.h (this directory is only on the include path of non-Windows builds).
//
//   files        CreateFileW / ReadFile / WriteFile / GetFileTime / FlushFileBuffers on a file descriptor
//   directories  CreateFileW(FILE_FLAG_BACKUP_SEMANTICS) + the synchronous ReadDirectoryChangesW, on inotify: one watch per
//                directory of the tree (new directories are added as they appear), events turned into
//                FILE_NOTIFY_INFORMATION records with the path relative to the watched directory in Windows spelling
//                (backslashes). The read waits in poll() with a short timeout so that CancelSynchronousIo (given the
//                std::thread::native_handle() of the reading thread) ends it with ERROR_OPERATION_ABORTED.
//   pipes        CreatePipe / PeekNamedPipe (FIONREAD) / ReadFile (0 bytes at the end = ERROR_BROKEN_PIPE, as on Windows)
//   processes    CreateProcessW on posix_spawn: the Windows command line is split the way the CRT does, the STARTUPINFO
//                std handles become the child's 0/1/2, the child gets its own process group (that is what a job kills).
//                A Windows .exe runs through WSL interop; its arguments that are absolute Linux paths are given to it as
//                Windows paths (/mnt/d/x -> D:\x, any other -> \\wsl.localhost\<distro>\...).
//                WaitForSingleObject / GetExitCodeProcess / TerminateProcess / OpenProcess / ResumeThread.
//   jobs         CreateJobObjectW / AssignProcessToJobObject / TerminateJobObject, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: the
//                process groups of the assigned processes are killed.
//
// A HANDLE from here points at a kernel::object (checked by a magic number); CloseHandle deletes it. Handles that did not
// come from here (null, INVALID_HANDLE_VALUE, the pseudo handles) are accepted by CloseHandle as before.
// GetLastError is per thread (and per binary: each engine library has its own copy, like any inline variable here).
//
#include <atomic>
#include <cerrno>
#include <chrono>
#include <climits>
#include <cstddef>
#include <cstring>
#include <ctime>
#include <deque>
#include <filesystem>
#include <mutex>
#include <string>
#include <string_view>
#include <thread>
#include <type_traits>
#include <unordered_map>
#include <utility>
#include <vector>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <spawn.h>
#include <sys/inotify.h>
#include <sys/ioctl.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef ERROR_PATH_NOT_FOUND
#define ERROR_PATH_NOT_FOUND        3L
#endif
#ifndef ERROR_INVALID_HANDLE
#define ERROR_INVALID_HANDLE        6L
#endif
#ifndef ERROR_GEN_FAILURE
#define ERROR_GEN_FAILURE           31L
#endif
#ifndef ERROR_FILE_EXISTS
#define ERROR_FILE_EXISTS           80L
#endif
#ifndef ERROR_INVALID_PARAMETER
#define ERROR_INVALID_PARAMETER     87L
#endif
#ifndef ERROR_ALREADY_EXISTS
#define ERROR_ALREADY_EXISTS        183L
#endif
#ifndef ERROR_NO_DATA
#define ERROR_NO_DATA               232L
#endif
#ifndef ERROR_NOT_FOUND
#define ERROR_NOT_FOUND             1168L
#endif
#ifndef FILE_NOTIFY_CHANGE_ATTRIBUTES
#define FILE_NOTIFY_CHANGE_ATTRIBUTES 0x00000004
#endif

namespace xlion_win32_shim::kernel
{
    inline thread_local DWORD t_LastError = 0;
    inline BOOL Fail(DWORD Error) noexcept { t_LastError = Error; return FALSE; }

    inline DWORD FromErrno(int e) noexcept
    {
        switch (e)
        {
            case ENOENT:                return ERROR_FILE_NOT_FOUND;
            case ENOTDIR:               return ERROR_PATH_NOT_FOUND;
            case EACCES: case EPERM:
            case EISDIR: case EROFS:    return ERROR_ACCESS_DENIED;
            case EEXIST:                return ERROR_FILE_EXISTS;
            case EPIPE:                 return ERROR_NO_DATA;
            case EBADF:                 return ERROR_INVALID_HANDLE;
            case EINVAL:                return ERROR_INVALID_PARAMETER;
            case ETXTBSY: case EBUSY:   return ERROR_SHARING_VIOLATION;
            default:                    return ERROR_GEN_FAILURE;
        }
    }

    //---------------------------------------------------------------------------------
    // UTF-8 <-> wchar_t (UTF-32 on Linux) without the locale (the C locale cannot convert non-ASCII)
    //---------------------------------------------------------------------------------
    inline std::string Utf8(std::wstring_view W)
    {
        std::string Out;
        Out.reserve(W.size());
        for (const wchar_t wc : W)
        {
            const auto c = static_cast<std::uint32_t>(wc);
            if      (c < 0x80)    Out.push_back(static_cast<char>(c));
            else if (c < 0x800)   { Out.push_back(static_cast<char>(0xC0 | (c >> 6)));  Out.push_back(static_cast<char>(0x80 | (c & 0x3F))); }
            else if (c < 0x10000) { Out.push_back(static_cast<char>(0xE0 | (c >> 12))); Out.push_back(static_cast<char>(0x80 | ((c >> 6) & 0x3F))); Out.push_back(static_cast<char>(0x80 | (c & 0x3F))); }
            else                  { Out.push_back(static_cast<char>(0xF0 | (c >> 18))); Out.push_back(static_cast<char>(0x80 | ((c >> 12) & 0x3F))); Out.push_back(static_cast<char>(0x80 | ((c >> 6) & 0x3F))); Out.push_back(static_cast<char>(0x80 | (c & 0x3F))); }
        }
        return Out;
    }

    inline std::wstring Wide(std::string_view S)
    {
        std::wstring Out;
        Out.reserve(S.size());
        for (std::size_t i = 0; i < S.size();)
        {
            const auto c = static_cast<unsigned char>(S[i]);
            std::uint32_t Code = c; int n = 0;
            if      (c >= 0xF0) { Code = c & 0x07; n = 3; }
            else if (c >= 0xE0) { Code = c & 0x0F; n = 2; }
            else if (c >= 0xC0) { Code = c & 0x1F; n = 1; }
            ++i;
            for (int k = 0; k < n && i < S.size(); ++k, ++i) Code = (Code << 6) | (static_cast<unsigned char>(S[i]) & 0x3F);
            Out.push_back(static_cast<wchar_t>(Code));
        }
        return Out;
    }

    // A path as the Windows-side code spells it, for the libc calls (the path compat layer resolves the case)
    inline std::string PathOf(std::wstring_view W)
    {
        std::string S = Utf8(W);
        for (auto& c : S) if (c == '\\') c = '/';
        return S;
    }

    inline std::wstring ToW(const wchar_t* p) { return p ? std::wstring(p) : std::wstring(); }
    inline std::wstring ToW(const char* p)    { return p ? Wide(p) : std::wstring(); }
    inline std::wstring ToW(std::nullptr_t)   { return {}; }
    template< typename T > requires std::is_integral_v<T> inline std::wstring ToW(T) { return {}; }      // NULL

    //---------------------------------------------------------------------------------
    // The objects behind the handles
    //---------------------------------------------------------------------------------
    enum class kind : std::uint32_t { file, directory, pipe, process, thread, job };
    inline constexpr std::uint32_t kMagic = 0x584B484Eu;

    struct object
    {
        std::uint32_t m_Magic = kMagic;
        kind          m_Kind;
        explicit object(kind K) noexcept : m_Kind(K) {}
        object(const object&) = delete;
        object& operator=(const object&) = delete;
        virtual ~object() { m_Magic = 0; }
    };

    struct fd_object final : object
    {
        int  m_Fd       = -1;
        bool m_bInherit = false;
        fd_object(kind K, int Fd) noexcept : object(K), m_Fd(Fd) {}
        ~fd_object() override { if (m_Fd >= 0) ::close(m_Fd); }
    };

    struct notify_record { DWORD m_Action; std::wstring m_Name; };

    struct directory_object final : object
    {
        std::string                          m_Path;                // the real path of the watched directory
        int                                  m_Inotify  = -1;
        bool                                 m_bSubtree = false;
        bool                                 m_bOverflow = false;
        bool                                 m_bFullWarned = false;
        DWORD                                m_Filter   = 0;
        std::unordered_map<int, std::string> m_Watches;             // watch descriptor -> directory relative to m_Path ("" = itself), '/' separators
        std::deque<notify_record>            m_Pending;
        std::mutex                           m_Mutex;
        directory_object() noexcept : object(kind::directory) {}
        ~directory_object() override { if (m_Inotify >= 0) ::close(m_Inotify); }
    };

    struct process_object final : object
    {
        pid_t      m_Pid;
        bool       m_bChild;                                        // ours (waitpid) or opened by id (only "is it alive")
        bool       m_bDone       = false;
        bool       m_bTerminated = false;
        DWORD      m_ExitCode    = STILL_ACTIVE;
        DWORD      m_TerminateCode = 0;
        std::mutex m_Mutex;
        process_object(pid_t Pid, bool bChild) noexcept : object(kind::process), m_Pid(Pid), m_bChild(bChild) {}
    };

    struct thread_object final : object
    {
        thread_object() noexcept : object(kind::thread) {}
    };

    struct job_object final : object
    {
        std::mutex         m_Mutex;
        std::vector<pid_t> m_Groups;                                // process group ids (each child leads its own)
        bool               m_bKillOnClose = false;
        job_object() noexcept : object(kind::job) {}
        void KillAll() noexcept
        {
            std::lock_guard Lock(m_Mutex);
            for (const pid_t g : m_Groups) { ::kill(-g, SIGKILL); ::kill(g, SIGKILL); }
            m_Groups.clear();
        }
        ~job_object() override { if (m_bKillOnClose) KillAll(); }
    };

    inline object* Get(HANDLE h) noexcept
    {
        const auto v = reinterpret_cast<std::intptr_t>(h);
        if (v == 0 || (v < 0 && v > -16)) return nullptr;           // null, INVALID_HANDLE_VALUE, the pseudo handles
        auto* p = static_cast<object*>(h);
        return p->m_Magic == kMagic ? p : nullptr;
    }
    template< typename T > inline T* As(HANDLE h, kind K) noexcept
    {
        auto* p = Get(h);
        return p && p->m_Kind == K ? static_cast<T*>(p) : nullptr;
    }
    inline fd_object* AsFd(HANDLE h) noexcept
    {
        auto* p = Get(h);
        return p && (p->m_Kind == kind::file || p->m_Kind == kind::pipe) ? static_cast<fd_object*>(p) : nullptr;
    }
    inline HANDLE ToHandle(object* p) noexcept { return static_cast<void*>(p); }

    //---------------------------------------------------------------------------------
    // CancelSynchronousIo: a flag per thread that a synchronous read in progress (or the next one) sees
    //---------------------------------------------------------------------------------
    struct cancel_registry { std::mutex m_Mutex; std::unordered_map<pthread_t, bool> m_Flags; };
    inline cancel_registry& Cancels() noexcept { static cancel_registry s; return s; }
    inline void RequestCancel(pthread_t Thread) { std::lock_guard Lock(Cancels().m_Mutex); Cancels().m_Flags[Thread] = true; }
    inline bool TakeCancel()
    {
        std::lock_guard Lock(Cancels().m_Mutex);
        auto It = Cancels().m_Flags.find(::pthread_self());
        if (It == Cancels().m_Flags.end()) return false;
        Cancels().m_Flags.erase(It);
        return true;
    }

    //---------------------------------------------------------------------------------
    // Directory watching on inotify
    //---------------------------------------------------------------------------------
    inline constexpr std::uint32_t kWatchMask = IN_CLOSE_WRITE | IN_MOVED_TO | IN_MOVED_FROM | IN_CREATE | IN_DELETE | IN_ATTRIB | IN_ONLYDIR | IN_DONT_FOLLOW;

    inline std::wstring WinName(const std::string& Rel)
    {
        std::wstring W = Wide(Rel);
        for (auto& c : W) if (c == L'/') c = L'\\';
        return W;
    }

    inline std::string Join(const std::string& Rel, std::string_view Name) { return Rel.empty() ? std::string(Name) : Rel + "/" + std::string(Name); }

    // Watches Rel (and, for a subtree watch, every directory below it). Files found in a directory that only now got its
    // watch are listed in pFound (they may have been written before the watch existed).
    inline void AddWatchTree(directory_object& D, const std::string& Rel, std::vector<std::string>* pFound)
    {
        const std::string Abs = Rel.empty() ? D.m_Path : D.m_Path + "/" + Rel;
        const int Wd = ::inotify_add_watch(D.m_Inotify, Abs.c_str(), kWatchMask);
        if (Wd < 0)
        {
            if (errno == ENOSPC && !D.m_bFullWarned) { D.m_bFullWarned = true; std::fprintf(stderr, "[win32 shim] inotify: out of watches (fs.inotify.max_user_watches) under %s\n", D.m_Path.c_str()); }
            return;
        }
        D.m_Watches[Wd] = Rel;
        if (!D.m_bSubtree && !Rel.empty()) return;
        std::error_code Ec;
        for (std::filesystem::directory_iterator It(Abs, Ec), End; !Ec && It != End; It.increment(Ec))
        {
            std::error_code Ec2;
            const auto Sub = Join(Rel, It->path().filename().string());
            if (It->is_symlink(Ec2)) continue;
            if (It->is_directory(Ec2)) { if (D.m_bSubtree) AddWatchTree(D, Sub, pFound); }
            else if (pFound) pFound->push_back(Sub);
        }
    }

    inline void ForgetTree(directory_object& D, const std::string& Rel)
    {
        for (auto It = D.m_Watches.begin(); It != D.m_Watches.end();)
        {
            if (It->second == Rel || It->second.starts_with(Rel + "/")) { ::inotify_rm_watch(D.m_Inotify, It->first); It = D.m_Watches.erase(It); }
            else ++It;
        }
    }

    inline void Queue(directory_object& D, DWORD Action, const std::string& Rel) { D.m_Pending.push_back({ Action, WinName(Rel) }); }

    // Everything inotify has for us now, as Windows actions (what the filter asks for)
    inline void Drain(directory_object& D)
    {
        const DWORD F         = D.m_Filter;
        const bool  bNames    = (F & FILE_NOTIFY_CHANGE_FILE_NAME) != 0;
        const bool  bDirNames = (F & FILE_NOTIFY_CHANGE_DIR_NAME) != 0;
        const bool  bWrites   = (F & (FILE_NOTIFY_CHANGE_LAST_WRITE | FILE_NOTIFY_CHANGE_SIZE | FILE_NOTIFY_CHANGE_CREATION)) != 0;
        const bool  bAttribs  = (F & FILE_NOTIFY_CHANGE_ATTRIBUTES) != 0;

        alignas(inotify_event) char Buffer[64 * 1024];
        for (;;)
        {
            const ssize_t n = ::read(D.m_Inotify, Buffer, sizeof(Buffer));
            if (n <= 0) break;
            for (ssize_t o = 0; o + static_cast<ssize_t>(sizeof(inotify_event)) <= n;)
            {
                const auto* pEv = reinterpret_cast<const inotify_event*>(Buffer + o);
                o += static_cast<ssize_t>(sizeof(inotify_event) + pEv->len);

                if (pEv->mask & IN_Q_OVERFLOW) { D.m_bOverflow = true; continue; }
                const auto It = D.m_Watches.find(pEv->wd);
                if (It == D.m_Watches.end()) continue;
                if (pEv->mask & IN_IGNORED) { D.m_Watches.erase(It); continue; }
                if (pEv->len == 0) continue;                                    // an event on the watched directory itself
                const std::string Rel = Join(It->second, pEv->name);

                if (pEv->mask & IN_ISDIR)
                {
                    if (pEv->mask & (IN_CREATE | IN_MOVED_TO))
                    {
                        if (bDirNames) Queue(D, (pEv->mask & IN_CREATE) ? FILE_ACTION_ADDED : FILE_ACTION_RENAMED_NEW_NAME, Rel);
                        if (D.m_bSubtree)
                        {
                            std::vector<std::string> Found;
                            AddWatchTree(D, Rel, &Found);
                            for (auto& S : Found)
                            {
                                if (bNames)       Queue(D, FILE_ACTION_ADDED, S);
                                else if (bWrites) Queue(D, FILE_ACTION_MODIFIED, S);
                            }
                        }
                    }
                    else if (pEv->mask & (IN_DELETE | IN_MOVED_FROM))
                    {
                        if (bDirNames) Queue(D, (pEv->mask & IN_DELETE) ? FILE_ACTION_REMOVED : FILE_ACTION_RENAMED_OLD_NAME, Rel);
                        ForgetTree(D, Rel);
                    }
                    continue;
                }

                if      (pEv->mask & IN_CLOSE_WRITE) { if (bWrites) Queue(D, FILE_ACTION_MODIFIED, Rel); }
                else if (pEv->mask & IN_CREATE)      { if (bNames)  Queue(D, FILE_ACTION_ADDED, Rel); }
                else if (pEv->mask & IN_DELETE)      { if (bNames)  Queue(D, FILE_ACTION_REMOVED, Rel); }
                else if (pEv->mask & IN_MOVED_FROM)  { if (bNames)  Queue(D, FILE_ACTION_RENAMED_OLD_NAME, Rel); }
                else if (pEv->mask & IN_MOVED_TO)                                   // a file saved by rename counts as written
                {
                    if (bNames)       Queue(D, FILE_ACTION_RENAMED_NEW_NAME, Rel);
                    else if (bWrites) Queue(D, FILE_ACTION_MODIFIED, Rel);
                }
                else if (pEv->mask & IN_ATTRIB)      { if (bAttribs || bWrites) Queue(D, FILE_ACTION_MODIFIED, Rel); }       // touch (a new write time) is an IN_ATTRIB: for Windows it is a change of the last write
            }
        }
    }

    // As many pending records as fit, chained the Windows way (DWORD aligned, NextEntryOffset 0 on the last)
    inline DWORD Fill(directory_object& D, void* pBuffer, DWORD Size) noexcept
    {
        auto* pOut  = static_cast<BYTE*>(pBuffer);
        DWORD Used  = 0;
        FILE_NOTIFY_INFORMATION* pPrev = nullptr;
        while (!D.m_Pending.empty())
        {
            const auto& R      = D.m_Pending.front();
            const auto  Bytes  = static_cast<DWORD>(R.m_Name.size() * sizeof(wchar_t));
            const auto  Header = static_cast<DWORD>(offsetof(FILE_NOTIFY_INFORMATION, FileName));
            const DWORD Record = (Header + Bytes + 3u) & ~3u;
            if (Used + Record > Size) break;
            auto* p = reinterpret_cast<FILE_NOTIFY_INFORMATION*>(pOut + Used);
            p->NextEntryOffset = 0;
            p->Action          = R.m_Action;
            p->FileNameLength  = Bytes;
            std::memcpy(pOut + Used + Header, R.m_Name.data(), Bytes);
            if (pPrev) pPrev->NextEntryOffset = static_cast<DWORD>(reinterpret_cast<BYTE*>(p) - reinterpret_cast<BYTE*>(pPrev));
            pPrev = p;
            Used += Record;
            D.m_Pending.pop_front();
        }
        if (Used == 0 && !D.m_Pending.empty()) D.m_Pending.pop_front();     // one record bigger than the buffer: Windows reports an overflow (0 bytes)
        return Used;
    }

    //---------------------------------------------------------------------------------
    // Processes
    //---------------------------------------------------------------------------------
    // The command line split the way the Microsoft CRT does (argv[0] has its own simpler rule)
    inline std::vector<std::wstring> SplitCommandLine(std::wstring_view S)
    {
        std::vector<std::wstring> Out;
        std::size_t i = 0;
        const auto Blank = [&](std::size_t k) { return k < S.size() && (S[k] == L' ' || S[k] == L'\t'); };
        while (Blank(i)) ++i;
        if (i < S.size())
        {
            std::wstring A;
            if (S[i] == L'"') { ++i; while (i < S.size() && S[i] != L'"') A.push_back(S[i++]); if (i < S.size()) ++i; }
            else              { while (i < S.size() && !Blank(i)) A.push_back(S[i++]); }
            Out.push_back(std::move(A));
        }
        for (;;)
        {
            while (Blank(i)) ++i;
            if (i >= S.size()) break;
            std::wstring A;
            bool bQuoted = false;
            while (i < S.size())
            {
                if (S[i] == L'\\')
                {
                    std::size_t k = 0;
                    while (i < S.size() && S[i] == L'\\') { ++k; ++i; }
                    if (i < S.size() && S[i] == L'"')
                    {
                        A.append(k / 2, L'\\');
                        if (k % 2) { A.push_back(L'"'); ++i; }
                    }
                    else A.append(k, L'\\');
                }
                else if (S[i] == L'"')
                {
                    if (bQuoted && i + 1 < S.size() && S[i + 1] == L'"') { A.push_back(L'"'); i += 2; continue; }
                    bQuoted = !bQuoted;
                    ++i;
                }
                else if (!bQuoted && Blank(i)) break;
                else A.push_back(S[i++]);
            }
            Out.push_back(std::move(A));
        }
        return Out;
    }

    inline bool EndsWithNoCase(std::string_view S, std::string_view End) noexcept
    {
        if (S.size() < End.size()) return false;
        for (std::size_t i = 0; i < End.size(); ++i)
            if (std::tolower(static_cast<unsigned char>(S[S.size() - End.size() + i])) != std::tolower(static_cast<unsigned char>(End[i]))) return false;
        return true;
    }

    // The real spelling of an existing path (case and backslashes resolved by the path compat layer), or the path as given
    inline std::string RealPath(const std::string& P)
    {
        char Buf[PATH_MAX];
        if (::realpath(P.c_str(), Buf)) return Buf;
        return P;
    }

    // A Linux path for a Windows program run through WSL interop: /mnt/d/x -> D:\x, any other absolute path -> \\wsl.localhost\<distro>\...
    // Only arguments whose first component exists at / are taken for paths (a Windows switch like /nodeReuse:false is not one).
    inline std::string WindowsArgument(const std::string& Arg)
    {
        if (Arg.size() < 2 || Arg[0] != '/' || Arg[1] == '/') return Arg;
        std::string P = Arg;
        for (auto& c : P) if (c == '\\') c = '/';
        const auto   Slash = P.find('/', 1);
        const auto   First = P.substr(0, Slash);
        struct stat  St;
        if (::stat(First.c_str(), &St) != 0 || !S_ISDIR(St.st_mode)) return Arg;

        std::string Out;
        if (P.size() >= 6 && P.compare(0, 5, "/mnt/") == 0 && std::isalpha(static_cast<unsigned char>(P[5])) && (P.size() == 6 || P[6] == '/'))
        {
            Out = std::string(1, static_cast<char>(std::toupper(static_cast<unsigned char>(P[5])))) + ":" + (P.size() > 6 ? P.substr(6) : std::string("/"));
        }
        else
        {
            const char* pDistro = std::getenv("WSL_DISTRO_NAME");
            if (!pDistro || !*pDistro) return Arg;
            Out = std::string("//wsl.localhost/") + pDistro + P;
        }
        for (auto& c : Out) if (c == '/') c = '\\';
        return Out;
    }

    inline bool IsWindowsProgram(const std::string& Path) noexcept { return EndsWithNoCase(Path, ".exe") || EndsWithNoCase(Path, ".com"); }

    // The environment block of CreateProcess ("K=V\0K=V\0\0", wide with CREATE_UNICODE_ENVIRONMENT)
    inline std::vector<std::string> EnvironmentOf(const void* pBlock, bool bWide)
    {
        std::vector<std::string> Out;
        if (bWide)
        {
            for (auto* p = static_cast<const wchar_t*>(pBlock); *p; p += std::wcslen(p) + 1) Out.push_back(Utf8(p));
        }
        else
        {
            for (auto* p = static_cast<const char*>(pBlock); *p; p += std::strlen(p) + 1) Out.emplace_back(p);
        }
        return Out;
    }

    inline BOOL CreateProcessCore(const std::wstring& Application, const std::wstring& CommandLine, DWORD Flags, const void* pEnvironment
                                 , const std::wstring& Directory, const STARTUPINFOW* pSi, PROCESS_INFORMATION* pPi)
    {
        if (pPi) std::memset(pPi, 0, sizeof(*pPi));
        auto Args = SplitCommandLine(CommandLine);
        if (!Application.empty()) { if (Args.empty()) Args.push_back(Application); }
        if (Args.empty()) return Fail(ERROR_INVALID_PARAMETER);

        std::string Program = PathOf(Application.empty() ? Args[0] : Application);
        if (Program.find('/') != std::string::npos) Program = RealPath(Program);
        const bool bWindows = IsWindowsProgram(Program);

        std::vector<std::string> Argv;
        Argv.push_back(Program.find('/') != std::string::npos ? Program : PathOf(Args[0]));
        for (std::size_t i = 1; i < Args.size(); ++i) Argv.push_back(bWindows ? WindowsArgument(Utf8(Args[i])) : Utf8(Args[i]));
        std::vector<char*> ArgvP;
        for (auto& A : Argv) ArgvP.push_back(A.data());
        ArgvP.push_back(nullptr);

        std::vector<std::string> Env;
        std::vector<char*>       EnvP;
        if (pEnvironment)
        {
            Env = EnvironmentOf(pEnvironment, (Flags & CREATE_UNICODE_ENVIRONMENT) != 0);
            for (auto& E : Env) EnvP.push_back(E.data());
            EnvP.push_back(nullptr);
        }

        posix_spawn_file_actions_t Actions;
        posix_spawnattr_t          Attr;
        ::posix_spawn_file_actions_init(&Actions);
        ::posix_spawnattr_init(&Attr);

        const bool bStd = pSi && (pSi->dwFlags & STARTF_USESTDHANDLES);
        const HANDLE Std[3] = { bStd ? pSi->hStdInput : nullptr, bStd ? pSi->hStdOutput : nullptr, bStd ? pSi->hStdError : nullptr };
        for (int n = 0; n < 3; ++n)
        {
            if (auto* pFd = AsFd(Std[n]))                       ::posix_spawn_file_actions_adddup2(&Actions, pFd->m_Fd, n);
            else if (n == 0 && (bStd || (Flags & DETACHED_PROCESS))) ::posix_spawn_file_actions_addopen(&Actions, 0, "/dev/null", O_RDONLY, 0);
        }
        std::string Cwd;
        if (!Directory.empty())
        {
            Cwd = RealPath(PathOf(Directory));
            ::posix_spawn_file_actions_addchdir_np(&Actions, Cwd.c_str());
        }

        // Its own process group (what a job kills), default signal handling for what a parent may ignore, nothing blocked
        sigset_t Default, Mask;
        sigemptyset(&Default); sigaddset(&Default, SIGPIPE); sigaddset(&Default, SIGINT); sigaddset(&Default, SIGTERM); sigaddset(&Default, SIGCHLD);
        sigemptyset(&Mask);
        ::posix_spawnattr_setsigdefault(&Attr, &Default);
        ::posix_spawnattr_setsigmask(&Attr, &Mask);
        ::posix_spawnattr_setpgroup(&Attr, 0);
        ::posix_spawnattr_setflags(&Attr, POSIX_SPAWN_SETPGROUP | POSIX_SPAWN_SETSIGDEF | POSIX_SPAWN_SETSIGMASK);

        pid_t Pid = 0;
        char** ppEnv = pEnvironment ? EnvP.data() : ::environ;
        const int Rc = Argv[0].find('/') != std::string::npos ? ::posix_spawn (&Pid, Argv[0].c_str(), &Actions, &Attr, ArgvP.data(), ppEnv)
                                                             : ::posix_spawnp(&Pid, Argv[0].c_str(), &Actions, &Attr, ArgvP.data(), ppEnv);
        ::posix_spawn_file_actions_destroy(&Actions);
        ::posix_spawnattr_destroy(&Attr);
        if (Rc != 0) return Fail(FromErrno(Rc));

        if (Flags & BELOW_NORMAL_PRIORITY_CLASS) ::setpriority(PRIO_PROCESS, static_cast<id_t>(Pid), 5);
        // CREATE_SUSPENDED: the child just runs (its process group already makes it part of whatever job it is assigned to next)
        if (pPi)
        {
            pPi->hProcess    = ToHandle(new process_object(Pid, true));
            pPi->hThread     = ToHandle(new thread_object());
            pPi->dwProcessId = static_cast<DWORD>(Pid);
            pPi->dwThreadId  = static_cast<DWORD>(Pid);
        }
        t_LastError = 0;
        return TRUE;
    }

    // Under the object's lock: has it ended (and with what code)?
    inline bool Reap(process_object& P) noexcept
    {
        if (P.m_bDone) return true;
        if (!P.m_bChild)
        {
            if (::kill(P.m_Pid, 0) != 0 && errno == ESRCH) { P.m_bDone = true; P.m_ExitCode = P.m_bTerminated ? P.m_TerminateCode : 0; }
            return P.m_bDone;
        }
        int   Status = 0;
        pid_t r;
        do r = ::waitpid(P.m_Pid, &Status, WNOHANG); while (r < 0 && errno == EINTR);
        if (r == P.m_Pid)
        {
            P.m_bDone    = true;
            P.m_ExitCode = P.m_bTerminated ? P.m_TerminateCode
                         : WIFEXITED(Status) ? static_cast<DWORD>(WEXITSTATUS(Status))
                         : static_cast<DWORD>(128 + (WIFSIGNALED(Status) ? WTERMSIG(Status) : 0));
        }
        else if (r < 0 && errno == ECHILD)                         // reaped by someone else (SIGCHLD ignored): the code is lost
        {
            P.m_bDone    = true;
            P.m_ExitCode = P.m_bTerminated ? P.m_TerminateCode : 0;
        }
        return P.m_bDone;
    }
}

//-------------------------------------------------------------------------------------
// The API
//-------------------------------------------------------------------------------------
inline DWORD GetLastError( void ) noexcept { return xlion_win32_shim::kernel::t_LastError; }
inline void  SetLastError( DWORD e ) noexcept { xlion_win32_shim::kernel::t_LastError = e; }

inline BOOL CloseHandle( HANDLE h ) noexcept
{
    if (auto* p = xlion_win32_shim::kernel::Get(h)) delete p;
    return TRUE;
}

inline HANDLE CreateFileUtf8( const std::string& Path, DWORD Access, DWORD Disposition, DWORD Flags ) noexcept
{
    namespace k = xlion_win32_shim::kernel;
    struct stat St;
    if (::stat(Path.c_str(), &St) == 0 && S_ISDIR(St.st_mode))
    {
        if (!(Flags & FILE_FLAG_BACKUP_SEMANTICS)) { k::t_LastError = ERROR_ACCESS_DENIED; return INVALID_HANDLE_VALUE; }
        auto* pDir = new k::directory_object();
        pDir->m_Path = k::RealPath(Path);
        k::t_LastError = 0;
        return k::ToHandle(pDir);
    }
    const bool bRead  = (Access & (GENERIC_READ | 0x0001u)) != 0;                 // FILE_READ_DATA
    const bool bWrite = (Access & (GENERIC_WRITE | 0x0002u | 0x0004u)) != 0;      // FILE_WRITE_DATA, FILE_APPEND_DATA
    int OFlags = O_CLOEXEC | ((bRead && bWrite) ? O_RDWR : bWrite ? O_WRONLY : O_RDONLY);
    switch (Disposition)
    {
        case CREATE_NEW:        OFlags |= O_CREAT | O_EXCL;  break;
        case CREATE_ALWAYS:     OFlags |= O_CREAT | O_TRUNC; break;
        case OPEN_ALWAYS:       OFlags |= O_CREAT;           break;
        case TRUNCATE_EXISTING: OFlags |= O_TRUNC;           break;
        default:                                             break;     // OPEN_EXISTING
    }
    const bool bExisted = (Disposition == CREATE_ALWAYS || Disposition == OPEN_ALWAYS) && ::access(Path.c_str(), F_OK) == 0;
    int Fd;
    do Fd = ::open(Path.c_str(), OFlags, 0666); while (Fd < 0 && errno == EINTR);
    if (Fd < 0) { k::t_LastError = k::FromErrno(errno); return INVALID_HANDLE_VALUE; }
    k::t_LastError = bExisted ? ERROR_ALREADY_EXISTS : 0;
    return k::ToHandle(new k::fd_object(k::kind::file, Fd));
}

template< typename C >
inline HANDLE CreateFileW( const C* pPath, DWORD Access, DWORD, LPSECURITY_ATTRIBUTES, DWORD Disposition, DWORD Flags, HANDLE ) noexcept
{
    if (!pPath) { SetLastError(ERROR_INVALID_PARAMETER); return INVALID_HANDLE_VALUE; }
    return CreateFileUtf8(xlion_win32_shim::kernel::PathOf(xlion_win32_shim::kernel::ToW(pPath)), Access, Disposition, Flags);
}
inline HANDLE CreateFileA( LPCSTR pPath, DWORD Access, DWORD Share, LPSECURITY_ATTRIBUTES pSa, DWORD Disposition, DWORD Flags, HANDLE hTemplate ) noexcept
{
    return CreateFileW(pPath, Access, Share, pSa, Disposition, Flags, hTemplate);
}

inline BOOL ReadFile( HANDLE h, LPVOID pBuffer, DWORD Size, LPDWORD pRead, LPOVERLAPPED ) noexcept
{
    namespace k = xlion_win32_shim::kernel;
    if (pRead) *pRead = 0;
    auto* F = k::AsFd(h);
    if (!F) return k::Fail(ERROR_INVALID_HANDLE);
    ssize_t r;
    do r = ::read(F->m_Fd, pBuffer, Size); while (r < 0 && errno == EINTR);
    if (r < 0) return k::Fail(k::FromErrno(errno));
    if (pRead) *pRead = static_cast<DWORD>(r);
    if (r == 0 && Size > 0 && F->m_Kind == k::kind::pipe) return k::Fail(ERROR_BROKEN_PIPE);   // every write end is closed
    k::t_LastError = 0;
    return TRUE;
}

inline BOOL WriteFile( HANDLE h, LPCVOID pBuffer, DWORD Size, LPDWORD pWritten, LPOVERLAPPED ) noexcept
{
    namespace k = xlion_win32_shim::kernel;
    if (pWritten) *pWritten = 0;
    auto* F = k::AsFd(h);
    if (!F) return k::Fail(ERROR_INVALID_HANDLE);
    DWORD Done = 0;
    while (Done < Size)
    {
        const ssize_t r = ::write(F->m_Fd, static_cast<const char*>(pBuffer) + Done, Size - Done);
        if (r < 0) { if (errno == EINTR) continue; if (pWritten) *pWritten = Done; return k::Fail(k::FromErrno(errno)); }
        Done += static_cast<DWORD>(r);
    }
    if (pWritten) *pWritten = Done;
    k::t_LastError = 0;
    return TRUE;
}

inline BOOL FlushFileBuffers( HANDLE h ) noexcept
{
    auto* F = xlion_win32_shim::kernel::AsFd(h);
    if (!F) return xlion_win32_shim::kernel::Fail(ERROR_INVALID_HANDLE);
    return ::fsync(F->m_Fd) == 0 || errno == EINVAL ? TRUE : xlion_win32_shim::kernel::Fail(xlion_win32_shim::kernel::FromErrno(errno));
}

inline BOOL GetFileTime( HANDLE h, LPFILETIME pCreation, LPFILETIME pAccess, LPFILETIME pWrite ) noexcept
{
    namespace k = xlion_win32_shim::kernel;
    auto* F = k::AsFd(h);
    struct stat St;
    if (!F) return k::Fail(ERROR_INVALID_HANDLE);
    if (::fstat(F->m_Fd, &St) != 0) return k::Fail(k::FromErrno(errno));
    const auto Set = [](LPFILETIME p, const timespec& T) noexcept
    {
        if (!p) return;
        const auto v = (static_cast<std::uint64_t>(T.tv_sec) + 11644473600ull) * 10000000ull + static_cast<std::uint64_t>(T.tv_nsec) / 100u;
        p->dwLowDateTime  = static_cast<DWORD>(v & 0xFFFFFFFFu);
        p->dwHighDateTime = static_cast<DWORD>(v >> 32);
    };
    Set(pCreation, St.st_ctim); Set(pAccess, St.st_atim); Set(pWrite, St.st_mtim);
    return TRUE;
}

// UTC, like on Windows (100 ns ticks since 1601-01-01)
inline BOOL FileTimeToSystemTime( const FILETIME* pTime, LPSYSTEMTIME pSystem ) noexcept
{
    if (!pTime || !pSystem) return xlion_win32_shim::kernel::Fail(ERROR_INVALID_PARAMETER);
    const std::uint64_t Ticks = (static_cast<std::uint64_t>(pTime->dwHighDateTime) << 32) | pTime->dwLowDateTime;
    const time_t        Secs  = static_cast<time_t>(static_cast<std::int64_t>(Ticks / 10000000ull) - 11644473600ll);
    std::tm T{};
    if (!::gmtime_r(&Secs, &T)) return xlion_win32_shim::kernel::Fail(ERROR_INVALID_PARAMETER);
    pSystem->wYear         = static_cast<WORD>(T.tm_year + 1900);
    pSystem->wMonth        = static_cast<WORD>(T.tm_mon + 1);
    pSystem->wDayOfWeek    = static_cast<WORD>(T.tm_wday);
    pSystem->wDay          = static_cast<WORD>(T.tm_mday);
    pSystem->wHour         = static_cast<WORD>(T.tm_hour);
    pSystem->wMinute       = static_cast<WORD>(T.tm_min);
    pSystem->wSecond       = static_cast<WORD>(T.tm_sec);
    pSystem->wMilliseconds = static_cast<WORD>((Ticks % 10000000ull) / 10000ull);
    return TRUE;
}

// The synchronous form only (no OVERLAPPED / completion routine): what the asset watchers use
inline BOOL ReadDirectoryChangesW( HANDLE h, LPVOID pBuffer, DWORD Size, BOOL bWatchSubtree, DWORD Filter, LPDWORD pReturned, LPOVERLAPPED pOverlapped, LPOVERLAPPED_COMPLETION_ROUTINE ) noexcept
{
    namespace k = xlion_win32_shim::kernel;
    if (pReturned) *pReturned = 0;
    auto* D = k::As<k::directory_object>(h, k::kind::directory);
    if (!D)          return k::Fail(ERROR_INVALID_HANDLE);
    if (pOverlapped) return k::Fail(ERROR_NOT_SUPPORTED);

    std::unique_lock Lock(D->m_Mutex);
    if (D->m_Inotify < 0)
    {
        D->m_Inotify = ::inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
        if (D->m_Inotify < 0) return k::Fail(k::FromErrno(errno));
        D->m_bSubtree = bWatchSubtree != FALSE;
        D->m_Filter   = Filter;
        k::AddWatchTree(*D, "", nullptr);
        if (D->m_Watches.empty()) return k::Fail(ERROR_ACCESS_DENIED);
    }
    D->m_Filter = Filter;
    for (;;)
    {
        if (!D->m_Pending.empty())
        {
            const DWORD n = k::Fill(*D, pBuffer, Size);
            if (pReturned) *pReturned = n;
            k::t_LastError = 0;
            return TRUE;
        }
        if (D->m_bOverflow) { D->m_bOverflow = false; k::t_LastError = 0; return TRUE; }   // 0 bytes: the caller has to look at everything again
        if (k::TakeCancel()) return k::Fail(ERROR_OPERATION_ABORTED);

        pollfd P{ D->m_Inotify, POLLIN, 0 };
        Lock.unlock();
        const int r = ::poll(&P, 1, 250);
        Lock.lock();
        if (r < 0 && errno != EINTR) return k::Fail(k::FromErrno(errno));
        if (r > 0) k::Drain(*D);
    }
}

// Given the std::thread::native_handle() of the reading thread (what the asset watchers pass)
template< typename T > requires std::is_integral_v<T>
inline BOOL CancelSynchronousIo( T Thread ) noexcept
{
    xlion_win32_shim::kernel::RequestCancel(static_cast<pthread_t>(Thread));
    return TRUE;
}
inline BOOL CancelSynchronousIo( HANDLE ) noexcept { return xlion_win32_shim::kernel::Fail(ERROR_NOT_FOUND); }

inline BOOL CreatePipe( HANDLE* pRead, HANDLE* pWrite, LPSECURITY_ATTRIBUTES pSa, DWORD ) noexcept
{
    namespace k = xlion_win32_shim::kernel;
    if (pRead)  *pRead  = nullptr;
    if (pWrite) *pWrite = nullptr;
    int Fds[2];
    if (!pRead || !pWrite) return k::Fail(ERROR_INVALID_PARAMETER);
    if (::pipe2(Fds, O_CLOEXEC) != 0) return k::Fail(k::FromErrno(errno));
    auto* R = new k::fd_object(k::kind::pipe, Fds[0]);
    auto* W = new k::fd_object(k::kind::pipe, Fds[1]);
    R->m_bInherit = W->m_bInherit = pSa && pSa->bInheritHandle;
    *pRead  = k::ToHandle(R);
    *pWrite = k::ToHandle(W);
    return TRUE;
}

inline BOOL PeekNamedPipe( HANDLE h, LPVOID, DWORD, LPDWORD pRead, LPDWORD pAvailable, LPDWORD pLeft ) noexcept
{
    namespace k = xlion_win32_shim::kernel;
    if (pRead) *pRead = 0;
    if (pAvailable) *pAvailable = 0;
    if (pLeft) *pLeft = 0;
    auto* F = k::AsFd(h);
    if (!F) return k::Fail(ERROR_INVALID_HANDLE);
    int Available = 0;
    if (::ioctl(F->m_Fd, FIONREAD, &Available) != 0) return k::Fail(k::FromErrno(errno));
    if (Available == 0)
    {
        pollfd P{ F->m_Fd, POLLIN, 0 };
        if (::poll(&P, 1, 0) > 0 && (P.revents & POLLHUP)) return k::Fail(ERROR_BROKEN_PIPE);
    }
    if (pAvailable) *pAvailable = static_cast<DWORD>(Available);    // the data itself is not peeked (pipes cannot): callers pass no buffer
    return TRUE;
}

inline BOOL SetHandleInformation( HANDLE h, DWORD Mask, DWORD Flags ) noexcept
{
    if (auto* F = xlion_win32_shim::kernel::AsFd(h)) { if (Mask & HANDLE_FLAG_INHERIT) F->m_bInherit = (Flags & HANDLE_FLAG_INHERIT) != 0; return TRUE; }
    return xlion_win32_shim::kernel::Fail(ERROR_INVALID_HANDLE);
}

// CreateProcess with whatever string types the caller has (nullptr, LPWSTR, path::c_str(), ...)
template< typename A, typename B, typename C >
inline BOOL CreateProcessW( A Application, B CommandLine, LPSECURITY_ATTRIBUTES, LPSECURITY_ATTRIBUTES, BOOL, DWORD Flags, LPVOID pEnvironment, C Directory, LPSTARTUPINFOW pSi, LPPROCESS_INFORMATION pPi ) noexcept
{
    namespace k = xlion_win32_shim::kernel;
    try
    {
        return k::CreateProcessCore(k::ToW(Application), k::ToW(CommandLine), Flags, pEnvironment, k::ToW(Directory), pSi, pPi);
    }
    catch (...) { return k::Fail(ERROR_GEN_FAILURE); }
}

inline DWORD WaitForSingleObject( HANDLE h, DWORD Milliseconds ) noexcept
{
    namespace k = xlion_win32_shim::kernel;
    auto* p = k::Get(h);
    if (!p) { k::t_LastError = ERROR_INVALID_HANDLE; return WAIT_FAILED; }
    if (p->m_Kind == k::kind::thread) return WAIT_OBJECT_0;
    if (p->m_Kind != k::kind::process) { k::t_LastError = ERROR_NOT_SUPPORTED; return WAIT_FAILED; }
    auto& P = *static_cast<k::process_object*>(p);
    const auto Start = std::chrono::steady_clock::now();
    for (int Nap = 1;; Nap = Nap < 50 ? Nap * 2 : 50)
    {
        {
            std::lock_guard Lock(P.m_Mutex);
            if (k::Reap(P)) return WAIT_OBJECT_0;
        }
        if (Milliseconds != INFINITE && std::chrono::steady_clock::now() - Start >= std::chrono::milliseconds(Milliseconds)) return WAIT_TIMEOUT;
        std::this_thread::sleep_for(std::chrono::milliseconds(Nap));
    }
}

inline BOOL GetExitCodeProcess( HANDLE h, LPDWORD pCode ) noexcept
{
    namespace k = xlion_win32_shim::kernel;
    auto* P = k::As<k::process_object>(h, k::kind::process);
    if (!P) { if (pCode) *pCode = 1; return k::Fail(ERROR_INVALID_HANDLE); }
    std::lock_guard Lock(P->m_Mutex);
    if (pCode) *pCode = k::Reap(*P) ? P->m_ExitCode : static_cast<DWORD>(STILL_ACTIVE);
    return TRUE;
}

inline BOOL TerminateProcess( HANDLE h, UINT Code ) noexcept
{
    namespace k = xlion_win32_shim::kernel;
    auto* P = k::As<k::process_object>(h, k::kind::process);
    if (!P) return k::Fail(ERROR_INVALID_HANDLE);
    std::lock_guard Lock(P->m_Mutex);
    if (P->m_bDone) return k::Fail(ERROR_ACCESS_DENIED);
    P->m_bTerminated   = true;
    P->m_TerminateCode = Code;
    return ::kill(P->m_Pid, SIGKILL) == 0 ? TRUE : k::Fail(k::FromErrno(errno));
}

inline HANDLE OpenProcess( DWORD, BOOL, DWORD Pid ) noexcept
{
    namespace k = xlion_win32_shim::kernel;
    if (Pid == 0 || (::kill(static_cast<pid_t>(Pid), 0) != 0 && errno == ESRCH)) { k::t_LastError = ERROR_INVALID_PARAMETER; return nullptr; }
    return k::ToHandle(new k::process_object(static_cast<pid_t>(Pid), false));
}

inline DWORD ResumeThread( HANDLE h ) noexcept
{
    // CreateProcess does not really suspend (see CreateProcessCore): report the one suspension that is lifted
    return xlion_win32_shim::kernel::As<xlion_win32_shim::kernel::thread_object>(h, xlion_win32_shim::kernel::kind::thread) ? 1u : static_cast<DWORD>(-1);
}

inline HANDLE CreateJobObjectW( LPSECURITY_ATTRIBUTES, LPCWSTR ) noexcept
{
    return xlion_win32_shim::kernel::ToHandle(new xlion_win32_shim::kernel::job_object());
}

inline BOOL SetInformationJobObject( HANDLE h, JOBOBJECTINFOCLASS Class, LPVOID pInfo, DWORD Size ) noexcept
{
    namespace k = xlion_win32_shim::kernel;
    auto* J = k::As<k::job_object>(h, k::kind::job);
    if (!J) return k::Fail(ERROR_INVALID_HANDLE);
    if (Class == JobObjectExtendedLimitInformation && pInfo && Size >= sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION))
        J->m_bKillOnClose = (static_cast<const JOBOBJECT_EXTENDED_LIMIT_INFORMATION*>(pInfo)->BasicLimitInformation.LimitFlags & JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE) != 0;
    return TRUE;
}

inline BOOL AssignProcessToJobObject( HANDLE hJob, HANDLE hProcess ) noexcept
{
    namespace k = xlion_win32_shim::kernel;
    auto* J = k::As<k::job_object>(hJob, k::kind::job);
    auto* P = k::As<k::process_object>(hProcess, k::kind::process);
    if (!J || !P) return k::Fail(ERROR_INVALID_HANDLE);
    std::lock_guard Lock(J->m_Mutex);
    J->m_Groups.push_back(P->m_Pid);                                // a child of CreateProcess leads its own process group
    return TRUE;
}

inline BOOL TerminateJobObject( HANDLE h, UINT ) noexcept
{
    namespace k = xlion_win32_shim::kernel;
    auto* J = k::As<k::job_object>(h, k::kind::job);
    if (!J) return k::Fail(ERROR_INVALID_HANDLE);
    J->KillAll();
    return TRUE;
}
