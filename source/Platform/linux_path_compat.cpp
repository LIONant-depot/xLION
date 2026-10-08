//
// Linux port (linux-headless branch): Windows-style path compatibility at the libc boundary.
//
// The editor, its plugins AND its data (descriptors, configs) spell paths the Windows way:
// "<project>\\Cache\\Resources\\Platforms\\WINDOWS\\..." - backslash separators and a case-insensitive
// file system ("cache\\plugins" for "Cache/Plugins"). Rewriting every such site (and the data) would be a
// large, risky change to code shared with the Windows build. Instead, on Linux only, this file interposes
// the path-taking libc functions inside the executable (it is compiled only into the Linux executables):
//
//   1. a path that contains '\\' has it turned into '/' before the call;
//   2. if the call then fails with ENOENT/ENOTDIR, the path is resolved component by component,
//      case-insensitively, against what is on disk, and the call is retried with the real spelling.
//
// Paths that already work on Linux are passed through untouched (one extra check of the string), so normal
// POSIX behaviour is unchanged. Set XLION_NO_PATH_COMPAT=1 to switch the translation off.
// Calls made by std::filesystem / fstream / fopen / the .so files all go through these definitions because
// the executable exports them (they are referenced by libstdc++/libc at link time).
//
#if !defined(_WIN32)
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include <dlfcn.h>
#include <dirent.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <errno.h>
#include <unistd.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <string>
#include <atomic>

namespace
{
    template< typename T >
    T Real( const char* pName ) noexcept
    {
        return reinterpret_cast<T>(::dlsym(RTLD_NEXT, pName));
    }

    #define XLION_REAL(NAME) static const auto s_##NAME = Real<decltype(&::NAME)>(#NAME)

    bool Enabled() noexcept
    {
        static const int s = [] { const char* p = ::getenv("XLION_NO_PATH_COMPAT"); return (p && *p == '1') ? 0 : 1; }();
        return s == 1;
    }

    using real_lstat_t    = int (*)(const char*, struct stat*);
    using real_opendir_t  = DIR* (*)(const char*);

    bool Exists( const std::string& P ) noexcept
    {
        static const auto s_lstat = Real<real_lstat_t>("lstat");
        struct stat St;
        return s_lstat(P.c_str(), &St) == 0;
    }

    // Case-insensitive resolution of P (already with '/' separators). Components that match nothing are
    // kept as they are (so a file about to be created keeps its name). Returns false when nothing changed.
    bool ResolveCase( const std::string& In, std::string& Out ) noexcept
    {
        static const auto s_opendir  = Real<real_opendir_t>("opendir");
        static const auto s_readdir  = Real<struct dirent* (*)(DIR*)>("readdir");
        static const auto s_closedir = Real<int (*)(DIR*)>("closedir");

        std::string Cur  = (!In.empty() && In[0] == '/') ? "/" : "";
        std::size_t i    = (Cur == "/") ? 1 : 0;
        bool        bChanged = false, bLost = false;
        while (i <= In.size())
        {
            std::size_t j = In.find('/', i);
            if (j == std::string::npos) j = In.size();
            std::string Part = In.substr(i, j - i);
            i = j + 1;
            if (Part.empty()) continue;
            std::string Next = Cur.empty() || Cur.back() == '/' ? Cur + Part : Cur + "/" + Part;
            if (!bLost && Part != "." && Part != ".." && !Exists(Next))
            {
                bool bFound = false;
                if (DIR* d = s_opendir(Cur.empty() ? "." : Cur.c_str()))
                {
                    while (struct dirent* e = s_readdir(d))
                    {
                        if (::strcasecmp(e->d_name, Part.c_str()) == 0)
                        {
                            Next = Cur.empty() || Cur.back() == '/' ? Cur + e->d_name : Cur + "/" + e->d_name;
                            bFound = bChanged = true;
                            break;
                        }
                    }
                    s_closedir(d);
                }
                if (!bFound) bLost = true;       // the rest does not exist: keep the remaining spelling
            }
            Cur = Next;
            if (j >= In.size()) break;
        }
        if (!In.empty() && In.back() == '/' && (Cur.empty() || Cur.back() != '/')) Cur += '/';
        Out = Cur;
        return bChanged;
    }

    // Step 1: separators. Returns the pointer to use for the first try.
    const char* Slashes( const char* p, std::string& Buf ) noexcept
    {
        if (!p || !Enabled() || !::strchr(p, '\\')) return p;
        Buf = p;
        for (auto& c : Buf) if (c == '\\') c = '/';
        return Buf.c_str();
    }

    // Step 2: after a failure, the case-resolved spelling (null when it would not change anything)
    const char* Cased( const char* p, std::string& Buf ) noexcept
    {
        if (!p || !Enabled() || (errno != ENOENT && errno != ENOTDIR)) return nullptr;
        std::string Out;
        if (!ResolveCase(p, Out)) return nullptr;
        Buf = std::move(Out);
        return Buf.c_str();
    }

    inline bool AtCwd( int Fd, const char* p ) noexcept { return Fd == AT_FDCWD || (p && p[0] == '/'); }
}

// Every wrapper: try with fixed separators; on ENOENT/ENOTDIR retry with the case-resolved path.
#define XLION_PATH_CALL(RET_T, FAIL_V, CALL)                                         \
    std::string B1, B2;                                                              \
    const char* p1 = Slashes(pPath, B1);                                             \
    RET_T r; { const char* pPath = p1; r = CALL; }                                   \
    if (r == FAIL_V) { const int e = errno;                                          \
        if (const char* p2 = Cased(p1, B2)) { const char* pPath = p2; r = CALL; }    \
        else errno = e; }                                                            \
    return r;

extern "C"
{
int open(const char* pPath, int Flags, ...)
{
    static const auto s_real = Real<int (*)(const char*, int, ...)>("open");
    mode_t Mode = 0;
    if (Flags & (O_CREAT | O_TMPFILE)) { va_list a; va_start(a, Flags); Mode = va_arg(a, mode_t); va_end(a); }
    XLION_PATH_CALL(int, -1, s_real(pPath, Flags, Mode))
}
int open64(const char* pPath, int Flags, ...)
{
    static const auto s_real = Real<int (*)(const char*, int, ...)>("open64");
    mode_t Mode = 0;
    if (Flags & (O_CREAT | O_TMPFILE)) { va_list a; va_start(a, Flags); Mode = va_arg(a, mode_t); va_end(a); }
    XLION_PATH_CALL(int, -1, s_real(pPath, Flags, Mode))
}
int openat(int Fd, const char* pPath, int Flags, ...)
{
    static const auto s_real = Real<int (*)(int, const char*, int, ...)>("openat");
    mode_t Mode = 0;
    if (Flags & (O_CREAT | O_TMPFILE)) { va_list a; va_start(a, Flags); Mode = va_arg(a, mode_t); va_end(a); }
    if (!AtCwd(Fd, pPath)) return s_real(Fd, pPath, Flags, Mode);
    XLION_PATH_CALL(int, -1, s_real(Fd, pPath, Flags, Mode))
}
int openat64(int Fd, const char* pPath, int Flags, ...)
{
    static const auto s_real = Real<int (*)(int, const char*, int, ...)>("openat64");
    mode_t Mode = 0;
    if (Flags & (O_CREAT | O_TMPFILE)) { va_list a; va_start(a, Flags); Mode = va_arg(a, mode_t); va_end(a); }
    if (!AtCwd(Fd, pPath)) return s_real(Fd, pPath, Flags, Mode);
    XLION_PATH_CALL(int, -1, s_real(Fd, pPath, Flags, Mode))
}
int creat(const char* pPath, mode_t Mode)                         { static const auto s_real = Real<int (*)(const char*, mode_t)>("creat"); XLION_PATH_CALL(int, -1, s_real(pPath, Mode)) }
FILE* fopen(const char* pPath, const char* pMode)                 { static const auto s_real = Real<FILE* (*)(const char*, const char*)>("fopen");   XLION_PATH_CALL(FILE*, nullptr, s_real(pPath, pMode)) }
FILE* fopen64(const char* pPath, const char* pMode)               { static const auto s_real = Real<FILE* (*)(const char*, const char*)>("fopen64"); XLION_PATH_CALL(FILE*, nullptr, s_real(pPath, pMode)) }
FILE* freopen(const char* pPath, const char* pMode, FILE* f)      { static const auto s_real = Real<FILE* (*)(const char*, const char*, FILE*)>("freopen"); if (!pPath) return s_real(pPath, pMode, f); XLION_PATH_CALL(FILE*, nullptr, s_real(pPath, pMode, f)) }
int stat(const char* pPath, struct stat* s)                       { static const auto s_real = Real<int (*)(const char*, struct stat*)>("stat");    XLION_PATH_CALL(int, -1, s_real(pPath, s)) }
int lstat(const char* pPath, struct stat* s)                      { static const auto s_real = Real<int (*)(const char*, struct stat*)>("lstat");   XLION_PATH_CALL(int, -1, s_real(pPath, s)) }
int stat64(const char* pPath, struct stat64* s)                   { static const auto s_real = Real<int (*)(const char*, struct stat64*)>("stat64");  XLION_PATH_CALL(int, -1, s_real(pPath, s)) }
int lstat64(const char* pPath, struct stat64* s)                  { static const auto s_real = Real<int (*)(const char*, struct stat64*)>("lstat64"); XLION_PATH_CALL(int, -1, s_real(pPath, s)) }
int fstatat(int Fd, const char* pPath, struct stat* s, int Fl)    { static const auto s_real = Real<int (*)(int, const char*, struct stat*, int)>("fstatat"); if (!AtCwd(Fd, pPath)) return s_real(Fd, pPath, s, Fl); XLION_PATH_CALL(int, -1, s_real(Fd, pPath, s, Fl)) }
int fstatat64(int Fd, const char* pPath, struct stat64* s, int Fl){ static const auto s_real = Real<int (*)(int, const char*, struct stat64*, int)>("fstatat64"); if (!AtCwd(Fd, pPath)) return s_real(Fd, pPath, s, Fl); XLION_PATH_CALL(int, -1, s_real(Fd, pPath, s, Fl)) }
int statx(int Fd, const char* pPath, int Fl, unsigned int M, struct statx* s) { static const auto s_real = Real<int (*)(int, const char*, int, unsigned int, struct statx*)>("statx"); if (!AtCwd(Fd, pPath)) return s_real(Fd, pPath, Fl, M, s); XLION_PATH_CALL(int, -1, s_real(Fd, pPath, Fl, M, s)) }
int access(const char* pPath, int M)                              { static const auto s_real = Real<int (*)(const char*, int)>("access"); XLION_PATH_CALL(int, -1, s_real(pPath, M)) }
int faccessat(int Fd, const char* pPath, int M, int Fl)           { static const auto s_real = Real<int (*)(int, const char*, int, int)>("faccessat"); if (!AtCwd(Fd, pPath)) return s_real(Fd, pPath, M, Fl); XLION_PATH_CALL(int, -1, s_real(Fd, pPath, M, Fl)) }
DIR* opendir(const char* pPath)                                   { static const auto s_real = Real<DIR* (*)(const char*)>("opendir"); XLION_PATH_CALL(DIR*, nullptr, s_real(pPath)) }
int mkdir(const char* pPath, mode_t M)                            { static const auto s_real = Real<int (*)(const char*, mode_t)>("mkdir"); XLION_PATH_CALL(int, -1, s_real(pPath, M)) }
int mkdirat(int Fd, const char* pPath, mode_t M)                  { static const auto s_real = Real<int (*)(int, const char*, mode_t)>("mkdirat"); if (!AtCwd(Fd, pPath)) return s_real(Fd, pPath, M); XLION_PATH_CALL(int, -1, s_real(Fd, pPath, M)) }
int rmdir(const char* pPath)                                      { static const auto s_real = Real<int (*)(const char*)>("rmdir");  XLION_PATH_CALL(int, -1, s_real(pPath)) }
int unlink(const char* pPath)                                     { static const auto s_real = Real<int (*)(const char*)>("unlink"); XLION_PATH_CALL(int, -1, s_real(pPath)) }
int unlinkat(int Fd, const char* pPath, int Fl)                   { static const auto s_real = Real<int (*)(int, const char*, int)>("unlinkat"); if (!AtCwd(Fd, pPath)) return s_real(Fd, pPath, Fl); XLION_PATH_CALL(int, -1, s_real(Fd, pPath, Fl)) }
int remove(const char* pPath)                                     { static const auto s_real = Real<int (*)(const char*)>("remove"); XLION_PATH_CALL(int, -1, s_real(pPath)) }
int chdir(const char* pPath)                                      { static const auto s_real = Real<int (*)(const char*)>("chdir");  XLION_PATH_CALL(int, -1, s_real(pPath)) }
int truncate(const char* pPath, off_t L)                          { static const auto s_real = Real<int (*)(const char*, off_t)>("truncate"); XLION_PATH_CALL(int, -1, s_real(pPath, L)) }
int chmod(const char* pPath, mode_t M)                            { static const auto s_real = Real<int (*)(const char*, mode_t)>("chmod"); XLION_PATH_CALL(int, -1, s_real(pPath, M)) }
// glibc declares utimensat's path nonnull, but the kernel takes NULL (it then works on Fd itself, as futimens does), so the test stays - out of line, where the compiler cannot drop it
[[gnu::noinline]] static bool IsNullPath(const char* p) noexcept { return p == nullptr; }
int utimensat(int Fd, const char* pPath, const struct timespec t[2], int Fl) { static const auto s_real = Real<int (*)(int, const char*, const struct timespec*, int)>("utimensat"); if (IsNullPath(pPath) || !AtCwd(Fd, pPath)) return s_real(Fd, pPath, t, Fl); XLION_PATH_CALL(int, -1, s_real(Fd, pPath, t, Fl)) }
ssize_t readlink(const char* pPath, char* b, size_t n)            { static const auto s_real = Real<ssize_t (*)(const char*, char*, size_t)>("readlink"); XLION_PATH_CALL(ssize_t, -1, s_real(pPath, b, n)) }
char* realpath(const char* pPath, char* pOut)                     { static const auto s_real = Real<char* (*)(const char*, char*)>("realpath"); XLION_PATH_CALL(char*, nullptr, s_real(pPath, pOut)) }

// Fortified variants (libstdc++'s directory_iterator calls __openat_2)
int __open_2(const char* pPath, int Flags)                        { static const auto s_real = Real<int (*)(const char*, int)>("__open_2");   XLION_PATH_CALL(int, -1, s_real(pPath, Flags)) }
int __open64_2(const char* pPath, int Flags)                      { static const auto s_real = Real<int (*)(const char*, int)>("__open64_2"); XLION_PATH_CALL(int, -1, s_real(pPath, Flags)) }
int __openat_2(int Fd, const char* pPath, int Flags)              { static const auto s_real = Real<int (*)(int, const char*, int)>("__openat_2");   if (!AtCwd(Fd, pPath)) return s_real(Fd, pPath, Flags); XLION_PATH_CALL(int, -1, s_real(Fd, pPath, Flags)) }
int __openat64_2(int Fd, const char* pPath, int Flags)            { static const auto s_real = Real<int (*)(int, const char*, int)>("__openat64_2"); if (!AtCwd(Fd, pPath)) return s_real(Fd, pPath, Flags); XLION_PATH_CALL(int, -1, s_real(Fd, pPath, Flags)) }
int statvfs(const char* pPath, struct statvfs* s)                 { static const auto s_real = Real<int (*)(const char*, struct statvfs*)>("statvfs"); XLION_PATH_CALL(int, -1, s_real(pPath, s)) }
// Two-path calls: only the SOURCE is case-resolved (the destination may not exist yet); both get '/'.
int rename(const char* pFrom, const char* pTo)
{
    static const auto s_real = Real<int (*)(const char*, const char*)>("rename");
    std::string B1, B2, B3;
    const char* pF = Slashes(pFrom, B1);
    const char* pT = Slashes(pTo, B2);
    int r = s_real(pF, pT);
    if (r == -1) { const int e = errno; if (const char* p2 = Cased(pF, B3)) r = s_real(p2, pT); else errno = e; }
    return r;
}
int renameat(int Fa, const char* pFrom, int Fb, const char* pTo)
{
    static const auto s_real = Real<int (*)(int, const char*, int, const char*)>("renameat");
    std::string B1, B2;
    return s_real(Fa, AtCwd(Fa, pFrom) ? Slashes(pFrom, B1) : pFrom, Fb, AtCwd(Fb, pTo) ? Slashes(pTo, B2) : pTo);
}
int symlink(const char* pTarget, const char* pLink)               { static const auto s_real = Real<int (*)(const char*, const char*)>("symlink"); std::string B1, B2; return s_real(Slashes(pTarget, B1), Slashes(pLink, B2)); }
int link(const char* pFrom, const char* pTo)                      { static const auto s_real = Real<int (*)(const char*, const char*)>("link");    std::string B1, B2; return s_real(Slashes(pFrom, B1), Slashes(pTo, B2)); }
}
#endif // !_WIN32