#pragma once
//
// Linux port (linux-headless branch): minimal <windows.h> stand-in.
//
// This directory is put on the include path ONLY for non-Windows builds (see the
// top-level CMakeLists.txt), so MSVC builds never see it. It lets editor/UI code
// that includes <windows.h> for cosmetic Win32 calls (monitor queries, cursor
// position, shell dialogs, ...) compile unchanged on Linux. The UI functions here are
// harmless stubs that report failure; none of them is reached by the headless editor. The graphical editor
// (xLION) links ../xlion_linux_gui.cpp, and the desktop ones (monitors, pointer, message box, file dialogs,
// ShellExecute) then really work on X11 - see the block at GetCursorPos.
// What headless really needs is implemented: dynamic libraries (round 3 below) and the
// kernel objects - files, directory watching, pipes, processes, jobs - in
// xlion_win32_kernel.h, included at the end.
//
#if defined(_WIN32)
#error "linux_win32_shim/windows.h must never be used on Windows"
#endif
#include <cstdint>
#include <cstddef>
#include <cwchar>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <unistd.h>
#include <vector>
#include <algorithm>
#include <cctype>

#ifndef WINAPI
#define WINAPI
#endif
#ifndef CALLBACK
#define CALLBACK
#endif
#ifndef APIENTRY
#define APIENTRY
#endif
#ifndef MAX_PATH
#define MAX_PATH 260
#endif
#ifndef TRUE
#define TRUE 1
#endif
#ifndef FALSE
#define FALSE 0
#endif

typedef int                 BOOL;
typedef unsigned char       BYTE;
typedef unsigned short      WORD;
typedef std::uint32_t       DWORD;
typedef std::uint32_t       UINT;
typedef std::int32_t        LONG;
typedef std::uint32_t       ULONG;
typedef std::int64_t        LONGLONG;
typedef std::uint64_t       ULONGLONG;
typedef std::uint64_t       DWORD64;
typedef std::intptr_t       LONG_PTR;
typedef std::uintptr_t      ULONG_PTR;
typedef std::uintptr_t      UINT_PTR;
typedef std::intptr_t       INT_PTR;
typedef ULONG_PTR           DWORD_PTR;
typedef ULONG_PTR           SIZE_T;
typedef LONG_PTR            LPARAM;
typedef UINT_PTR            WPARAM;
typedef LONG_PTR            LRESULT;
typedef LONG                HRESULT;
typedef char                CHAR;
typedef wchar_t             WCHAR;
typedef const char*         LPCSTR;
typedef char*               LPSTR;
typedef const wchar_t*      LPCWSTR;
typedef wchar_t*            LPWSTR;
typedef void*               LPVOID;
typedef const void*         LPCVOID;
typedef DWORD*              LPDWORD;
typedef void*               HANDLE;
typedef struct HWND__*      HWND;
typedef struct HMONITOR__*  HMONITOR;
typedef struct HINSTANCE__* HINSTANCE;
typedef HINSTANCE           HMODULE;
typedef struct HDC__*       HDC;
typedef struct HICON__*     HICON;
typedef struct HCURSOR__*   HCURSOR;

#define INVALID_HANDLE_VALUE  (reinterpret_cast<HANDLE>(static_cast<std::intptr_t>(-1)))
#define S_OK                  ((HRESULT)0L)
#define E_FAIL                ((HRESULT)0x80004005L)
#define SUCCEEDED(hr)         (((HRESULT)(hr)) >= 0)
#define FAILED(hr)            (((HRESULT)(hr)) < 0)

struct POINT { LONG x, y; };
struct RECT  { LONG left, top, right, bottom; };
typedef POINT* LPPOINT;
typedef RECT*  LPRECT;

struct MONITORINFO   { DWORD cbSize; RECT rcMonitor; RECT rcWork; DWORD dwFlags; };
typedef MONITORINFO* LPMONITORINFO;
#define MONITOR_DEFAULTTONULL     0x00000000
#define MONITOR_DEFAULTTOPRIMARY  0x00000001
#define MONITOR_DEFAULTTONEAREST  0x00000002

// ---------------------------------------------------------------------------------
// The desktop (monitors, pointer, message box, file dialogs, ShellExecute) goes to the graphical editor's X11 layer
// (../xlion_linux_gui.h) when it is linked in - only xLION links it; its entry points are weak, so everywhere else
// (xLION_Headless, the engine libraries) they are null and these functions fail the way they always did.
// HMONITOR is the 1-based index of the monitor in xlion_gui_EnumMonitors' list.
// ---------------------------------------------------------------------------------
#include "../xlion_linux_gui.h"
#include <string>
namespace xlion_win32_shim
{
    // UTF-32 wchar_t (Linux) -> UTF-8
    inline std::string ToUtf8( const wchar_t* p )
    {
        std::string S;
        if (!p) return S;
        for (; *p; ++p)
        {
            const auto c = static_cast<std::uint32_t>(*p);
            if      (c < 0x80)    S += static_cast<char>(c);
            else if (c < 0x800)   { S += static_cast<char>(0xC0 | (c >> 6));  S += static_cast<char>(0x80 | (c & 0x3F)); }
            else if (c < 0x10000) { S += static_cast<char>(0xE0 | (c >> 12)); S += static_cast<char>(0x80 | ((c >> 6) & 0x3F)); S += static_cast<char>(0x80 | (c & 0x3F)); }
            else                  { S += static_cast<char>(0xF0 | (c >> 18)); S += static_cast<char>(0x80 | ((c >> 12) & 0x3F)); S += static_cast<char>(0x80 | ((c >> 6) & 0x3F)); S += static_cast<char>(0x80 | (c & 0x3F)); }
        }
        return S;
    }
    inline std::string ToUtf8( const char* p )   { return p ? std::string(p) : std::string{}; }
    inline std::string ToUtf8( std::nullptr_t )  { return {}; }
    inline std::wstring FromUtf8( const std::string& S )
    {
        std::wstring W;
        for (std::size_t i = 0; i < S.size();)
        {
            const auto c = static_cast<unsigned char>(S[i]);
            std::uint32_t u = c; int n = 0;
            if      (c >= 0xF0) { u = c & 0x07; n = 3; }
            else if (c >= 0xE0) { u = c & 0x0F; n = 2; }
            else if (c >= 0xC0) { u = c & 0x1F; n = 1; }
            ++i;
            for (; n > 0 && i < S.size(); --n, ++i) u = (u << 6) | (static_cast<unsigned char>(S[i]) & 0x3F);
            W += static_cast<wchar_t>(u);
        }
        return W;
    }
    // The monitors now (index 0 = primary); empty without the graphical layer or a display
    inline int Monitors( xlion_gui_monitor* pOut, int Max ) noexcept { return xlion_gui_EnumMonitors ? xlion_gui_EnumMonitors(pOut, Max) : 0; }
}
inline BOOL     GetCursorPos      ( LPPOINT p )                     noexcept
{
    int x = 0, y = 0;
    if (p && xlion_gui_GetCursorPos && xlion_gui_GetCursorPos(&x, &y)) { p->x = x; p->y = y; return TRUE; }
    if (p) { p->x = p->y = 0; }
    return FALSE;
}
inline HMONITOR MonitorFromPoint  ( POINT At, DWORD Flags )         noexcept
{
    xlion_gui_monitor M[16];
    const int n = xlion_win32_shim::Monitors(M, 16);
    if (n <= 0) return nullptr;
    int Best = -1; long long BestDist = 0;
    for (int i = 0; i < n; ++i)
    {
        const long long dx = At.x < M[i].m_X ? M[i].m_X - At.x : (At.x >= M[i].m_X + M[i].m_W ? At.x - (M[i].m_X + M[i].m_W - 1) : 0);
        const long long dy = At.y < M[i].m_Y ? M[i].m_Y - At.y : (At.y >= M[i].m_Y + M[i].m_H ? At.y - (M[i].m_Y + M[i].m_H - 1) : 0);
        const long long d  = dx * dx + dy * dy;
        if (d == 0) return reinterpret_cast<HMONITOR>(static_cast<std::intptr_t>(i + 1));
        if (Best < 0 || d < BestDist) { Best = i; BestDist = d; }
    }
    if (Flags == MONITOR_DEFAULTTONULL)    return nullptr;
    if (Flags == MONITOR_DEFAULTTOPRIMARY) return reinterpret_cast<HMONITOR>(static_cast<std::intptr_t>(1));
    return reinterpret_cast<HMONITOR>(static_cast<std::intptr_t>(Best + 1));
}
inline HMONITOR MonitorFromWindow ( HWND, DWORD )                   noexcept { xlion_gui_monitor M[1]; return xlion_win32_shim::Monitors(M, 1) > 0 ? reinterpret_cast<HMONITOR>(static_cast<std::intptr_t>(1)) : nullptr; }
inline BOOL     GetMonitorInfoW   ( HMONITOR h, LPMONITORINFO p )   noexcept
{
    xlion_gui_monitor M[16];
    const int n = xlion_win32_shim::Monitors(M, 16);
    const auto i = static_cast<int>(reinterpret_cast<std::intptr_t>(h)) - 1;
    if (!p || i < 0 || i >= n) return FALSE;
    p->rcMonitor = RECT{ M[i].m_X, M[i].m_Y, M[i].m_X + M[i].m_W, M[i].m_Y + M[i].m_H };
    p->rcWork    = RECT{ M[i].m_WorkX, M[i].m_WorkY, M[i].m_WorkX + M[i].m_WorkW, M[i].m_WorkY + M[i].m_WorkH };
    p->dwFlags   = M[i].m_bPrimary ? 1u /*MONITORINFOF_PRIMARY*/ : 0u;
    return TRUE;
}
inline BOOL     GetMonitorInfoA   ( HMONITOR h, LPMONITORINFO p )   noexcept { return GetMonitorInfoW(h, p); }
#define GetMonitorInfo GetMonitorInfoW
inline void     Sleep             ( DWORD ms )                      noexcept { ::usleep(static_cast<useconds_t>(ms) * 1000u); }
inline void     OutputDebugStringA( LPCSTR )                        noexcept {}
inline void     OutputDebugStringW( LPCWSTR )                       noexcept {}
#define OutputDebugString OutputDebugStringW
inline BOOL     IsDebuggerPresent ( void )                          noexcept { return FALSE; }
// ---------------------------------------------------------------------------------
// kernel32-style types, constants and the stubs that still report failure (the real ones: xlion_win32_kernel.h)
// ---------------------------------------------------------------------------------
struct FILETIME   { DWORD dwLowDateTime, dwHighDateTime; };
struct SYSTEMTIME { WORD wYear, wMonth, wDayOfWeek, wDay, wHour, wMinute, wSecond, wMilliseconds; };
typedef FILETIME*   LPFILETIME;
typedef SYSTEMTIME* LPSYSTEMTIME;
union LARGE_INTEGER { struct { DWORD LowPart; LONG HighPart; }; LONGLONG QuadPart; };
struct SECURITY_ATTRIBUTES { DWORD nLength; LPVOID lpSecurityDescriptor; BOOL bInheritHandle; };
typedef SECURITY_ATTRIBUTES* LPSECURITY_ATTRIBUTES;
struct OVERLAPPED { ULONG_PTR Internal, InternalHigh; DWORD Offset, OffsetHigh; HANDLE hEvent; };
typedef OVERLAPPED* LPOVERLAPPED;
typedef void (*LPOVERLAPPED_COMPLETION_ROUTINE)(DWORD, DWORD, LPOVERLAPPED);
struct FILE_NOTIFY_INFORMATION { DWORD NextEntryOffset; DWORD Action; DWORD FileNameLength; WCHAR FileName[1]; };
struct STARTUPINFOW { DWORD cb; LPWSTR lpReserved, lpDesktop, lpTitle; DWORD dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags; WORD wShowWindow, cbReserved2; BYTE* lpReserved2; HANDLE hStdInput, hStdOutput, hStdError; };
struct STARTUPINFOA { DWORD cb; LPSTR  lpReserved, lpDesktop, lpTitle; DWORD dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags; WORD wShowWindow, cbReserved2; BYTE* lpReserved2; HANDLE hStdInput, hStdOutput, hStdError; };
typedef STARTUPINFOW STARTUPINFO;
typedef STARTUPINFOW* LPSTARTUPINFOW;
typedef STARTUPINFOA* LPSTARTUPINFOA;
struct PROCESS_INFORMATION { HANDLE hProcess, hThread; DWORD dwProcessId, dwThreadId; };
typedef PROCESS_INFORMATION* LPPROCESS_INFORMATION;

#define GENERIC_READ                  0x80000000u
#define GENERIC_WRITE                 0x40000000u
#define FILE_SHARE_READ               0x00000001
#define FILE_SHARE_WRITE              0x00000002
#define FILE_SHARE_DELETE             0x00000004
#define FILE_LIST_DIRECTORY           0x0001
#define CREATE_NEW                    1
#define CREATE_ALWAYS                 2
#define OPEN_EXISTING                 3
#define OPEN_ALWAYS                   4
#define TRUNCATE_EXISTING             5
#define FILE_ATTRIBUTE_NORMAL         0x00000080
#define FILE_ATTRIBUTE_DIRECTORY      0x00000010
#define INVALID_FILE_ATTRIBUTES       ((DWORD)-1)
#define FILE_FLAG_BACKUP_SEMANTICS    0x02000000
#define FILE_FLAG_OVERLAPPED          0x40000000
#define FILE_NOTIFY_CHANGE_FILE_NAME  0x00000001
#define FILE_NOTIFY_CHANGE_DIR_NAME   0x00000002
#define FILE_NOTIFY_CHANGE_SIZE       0x00000008
#define FILE_NOTIFY_CHANGE_LAST_WRITE 0x00000010
#define FILE_NOTIFY_CHANGE_CREATION   0x00000040
#define FILE_ACTION_ADDED             0x00000001
#define FILE_ACTION_REMOVED           0x00000002
#define FILE_ACTION_MODIFIED          0x00000003
#define FILE_ACTION_RENAMED_OLD_NAME  0x00000004
#define FILE_ACTION_RENAMED_NEW_NAME  0x00000005
#define ERROR_SUCCESS                 0L
#define ERROR_FILE_NOT_FOUND          2L
#define ERROR_ACCESS_DENIED           5L
#define ERROR_BROKEN_PIPE             109L
#define ERROR_IO_PENDING              997L
#define ERROR_OPERATION_ABORTED       995L
#define ERROR_PIPE_CONNECTED          535L
#define ERROR_MORE_DATA               234L
#define ERROR_NOT_SUPPORTED           50L
#define HANDLE_FLAG_INHERIT           0x00000001
#define STARTF_USESHOWWINDOW          0x00000001
#define STARTF_USESTDHANDLES          0x00000100
#define SW_HIDE                       0
#define SW_SHOW                       5
#define SW_SHOWNORMAL                 1
#define SW_RESTORE                    9
#define CREATE_NO_WINDOW              0x08000000
#define CREATE_SUSPENDED              0x00000004
#define CREATE_NEW_CONSOLE            0x00000010
#define CREATE_UNICODE_ENVIRONMENT    0x00000400
#define DETACHED_PROCESS              0x00000008
#define BELOW_NORMAL_PRIORITY_CLASS   0x00004000
#define NORMAL_PRIORITY_CLASS         0x00000020
#define INFINITE                      0xFFFFFFFFu
#define WAIT_OBJECT_0                 0x00000000L
#define WAIT_TIMEOUT                  258L
#define WAIT_FAILED                   ((DWORD)0xFFFFFFFF)
#define STILL_ACTIVE                  259L
#define PROCESS_QUERY_LIMITED_INFORMATION 0x1000
#define PROCESS_TERMINATE             0x0001
#define SYNCHRONIZE                   0x00100000L
#define STD_INPUT_HANDLE              ((DWORD)-10)
#define STD_OUTPUT_HANDLE             ((DWORD)-11)
#define STD_ERROR_HANDLE              ((DWORD)-12)
#define CP_UTF8                       65001
#define CP_ACP                        0

#define CreateFile CreateFileW
inline BOOL   CancelIoEx( HANDLE, LPOVERLAPPED ) noexcept { return FALSE; }
inline BOOL   CancelIo( HANDLE ) noexcept { return FALSE; }
inline BOOL   GetOverlappedResult( HANDLE, LPOVERLAPPED, LPDWORD n, BOOL ) noexcept { if (n) *n = 0; return FALSE; }
inline HANDLE CreateEventW( LPSECURITY_ATTRIBUTES, BOOL, BOOL, LPCWSTR ) noexcept { return nullptr; }
inline HANDLE CreateEventA( LPSECURITY_ATTRIBUTES, BOOL, BOOL, LPCSTR ) noexcept { return nullptr; }
#define CreateEvent CreateEventW
inline BOOL   SetEvent( HANDLE ) noexcept { return FALSE; }
inline BOOL   ResetEvent( HANDLE ) noexcept { return FALSE; }
inline DWORD  WaitForMultipleObjects( DWORD, const HANDLE*, BOOL, DWORD ) noexcept { return WAIT_FAILED; }
inline BOOL   CreateProcessA( LPCSTR,  LPSTR,  LPSECURITY_ATTRIBUTES, LPSECURITY_ATTRIBUTES, BOOL, DWORD, LPVOID, LPCSTR,  LPSTARTUPINFOA, LPPROCESS_INFORMATION pi ) noexcept { if (pi) std::memset(pi, 0, sizeof(*pi)); return FALSE; }
#define CreateProcess CreateProcessW
inline HANDLE GetCurrentProcess( void ) noexcept { return reinterpret_cast<HANDLE>(static_cast<std::intptr_t>(-1)); }
inline HANDLE GetCurrentThread( void ) noexcept { return reinterpret_cast<HANDLE>(static_cast<std::intptr_t>(-2)); }
inline DWORD  GetCurrentProcessId( void ) noexcept { return static_cast<DWORD>(::getpid()); }
inline HANDLE GetStdHandle( DWORD ) noexcept { return INVALID_HANDLE_VALUE; }
inline BOOL   SetCurrentDirectoryW( LPCWSTR ) noexcept { return FALSE; }
inline BOOL   SetCurrentDirectoryA( LPCSTR p ) noexcept { return p && ::chdir(p) == 0; }
#define SetCurrentDirectory SetCurrentDirectoryW
inline DWORD  GetCurrentDirectoryW( DWORD, LPWSTR b ) noexcept { if (b) b[0] = 0; return 0; }
#define GetCurrentDirectory GetCurrentDirectoryW
inline LPWSTR GetCommandLineW( void ) noexcept { static wchar_t s[1] = { 0 }; return s; }
inline DWORD  GetEnvironmentVariableA( LPCSTR, LPSTR b, DWORD ) noexcept { if (b) b[0] = 0; return 0; }
inline BOOL   SetEnvironmentVariableW( LPCWSTR, LPCWSTR ) noexcept { return FALSE; }
inline void*  LocalFree( void* p ) noexcept { std::free(p); return nullptr; }   // pairs with CommandLineToArgvW below
inline int    MultiByteToWideChar( UINT, DWORD, LPCSTR, int, LPWSTR, int ) noexcept { return 0; }
inline int    WideCharToMultiByte( UINT, DWORD, LPCWSTR, int, LPSTR, int, LPCSTR, BOOL* ) noexcept { return 0; }

// ---------------------------------------------------------------------------------
// user32 / shell32 style stubs
// ---------------------------------------------------------------------------------
#define HWND_TOP        (reinterpret_cast<HWND>(0))
#define HWND_TOPMOST    (reinterpret_cast<HWND>(static_cast<std::intptr_t>(-1)))
#define SWP_NOSIZE      0x0001
#define SWP_NOMOVE      0x0002
#define SWP_NOZORDER    0x0004
#define SWP_NOACTIVATE  0x0010
#define SWP_SHOWWINDOW  0x0040
#define MB_OK           0x00000000L
#define MB_ICONERROR    0x00000010L
#define MB_ICONWARNING  0x00000030L
#define MB_YESNO        0x00000004L
#define MB_OKCANCEL     0x00000001L
#define MB_YESNOCANCEL  0x00000003L
#define MB_ICONQUESTION 0x00000020L
#define MB_ICONINFORMATION 0x00000040L
#define IDOK            1
#define IDCANCEL        2
#define IDYES           6
#define IDNO            7
#define WM_CLOSE        0x0010
#define WM_QUIT         0x0012
inline BOOL     ShowWindow( HWND, int ) noexcept { return FALSE; }
inline BOOL     SetForegroundWindow( HWND ) noexcept { return FALSE; }
inline HWND     GetActiveWindow( void ) noexcept { return nullptr; }
inline HWND     GetForegroundWindow( void ) noexcept { return nullptr; }
inline BOOL     SetWindowPos( HWND, HWND, int, int, int, int, UINT ) noexcept { return FALSE; }
inline BOOL     GetWindowRect( HWND, LPRECT r ) noexcept { if (r) std::memset(r, 0, sizeof(*r)); return FALSE; }
inline int      GetWindowTextLengthW( HWND ) noexcept { return 0; }
inline DWORD    GetWindowThreadProcessId( HWND, LPDWORD p ) noexcept { if (p) *p = 0; return 0; }
inline BOOL     PostMessageW( HWND, UINT, WPARAM, LPARAM ) noexcept { return FALSE; }
inline int      MessageBoxA( HWND, LPCSTR pText, LPCSTR pCaption, UINT Type ) noexcept { return xlion_gui_MessageBox ? xlion_gui_MessageBox(pText, pCaption, Type) : 0; }
inline int      MessageBoxW( HWND, LPCWSTR pText, LPCWSTR pCaption, UINT Type ) noexcept
{
    if (!xlion_gui_MessageBox) return 0;
    return xlion_gui_MessageBox(xlion_win32_shim::ToUtf8(pText).c_str(), xlion_win32_shim::ToUtf8(pCaption).c_str(), Type);
}
#define MessageBox MessageBoxW
inline BOOL     SetCursorPos( int, int ) noexcept { return FALSE; }
// ShellExecute "open"/"explore"/"edit": the desktop's default application (> 32 = started, as on Windows; 2 = not)
inline HINSTANCE ShellExecuteA( HWND, LPCSTR, LPCSTR pFile, LPCSTR pParams, LPCSTR pDir, int ) noexcept
{
    const bool bOk = xlion_gui_ShellOpen && xlion_gui_ShellOpen(pFile, pParams, pDir);
    return reinterpret_cast<HINSTANCE>(static_cast<std::intptr_t>(bOk ? 42 : 2));
}
#define ShellExecute ShellExecuteW
// ---------------------------------------------------------------------------------
// round 2 (linux-headless port)
// ---------------------------------------------------------------------------------
#ifndef ZeroMemory
#define ZeroMemory(p, n) std::memset((p), 0, (n))
#endif
// Overloads that accept whatever handle/path type the caller has (std::thread::native_handle(), path::c_str())
inline BOOL PathMatchSpecW( LPCWSTR, LPCWSTR ) noexcept { return FALSE; }
inline BOOL IsIconic( HWND ) noexcept { return FALSE; }
inline HWND FindWindowExW( HWND, HWND, LPCWSTR, LPCWSTR ) noexcept { return nullptr; }
#define FindWindowEx FindWindowExW
typedef BOOL (*MONITORENUMPROC)(HMONITOR, HDC, LPRECT, LPARAM);
inline BOOL EnumDisplayMonitors( HDC, const RECT*, MONITORENUMPROC pProc, LPARAM Param ) noexcept
{
    xlion_gui_monitor M[16];
    const int n = xlion_win32_shim::Monitors(M, 16);
    if (n <= 0 || !pProc) return FALSE;
    for (int i = 0; i < n; ++i)
    {
        RECT R{ M[i].m_X, M[i].m_Y, M[i].m_X + M[i].m_W, M[i].m_Y + M[i].m_H };
        if (!pProc(reinterpret_cast<HMONITOR>(static_cast<std::intptr_t>(i + 1)), nullptr, &R, Param)) break;
    }
    return TRUE;
}
struct OPENFILENAMEW { DWORD lStructSize; HWND hwndOwner; HINSTANCE hInstance; LPCWSTR lpstrFilter; LPWSTR lpstrCustomFilter; DWORD nMaxCustFilter; DWORD nFilterIndex; LPWSTR lpstrFile; DWORD nMaxFile; LPWSTR lpstrFileTitle; DWORD nMaxFileTitle; LPCWSTR lpstrInitialDir; LPCWSTR lpstrTitle; DWORD Flags; WORD nFileOffset; WORD nFileExtension; LPCWSTR lpstrDefExt; LPARAM lCustData; void* lpfnHook; LPCWSTR lpTemplateName; void* pvReserved; DWORD dwReserved; DWORD FlagsEx; };
#define OFN_PATHMUSTEXIST   0x00000800
#define OFN_FILEMUSTEXIST   0x00001000
#define OFN_OVERWRITEPROMPT 0x00000002
#define OFN_NOCHANGEDIR     0x00000008
// The open/save dialogs of the desktop (zenity/kdialog through ../xlion_linux_gui.h); FALSE = cancelled or none available
inline BOOL ShimFileDialog( OPENFILENAMEW* p, int Mode ) noexcept
{
    if (!p || !p->lpstrFile || p->nMaxFile == 0 || !xlion_gui_FileDialog) return FALSE;
    std::string Filter;                                                     // "Name\0Spec\0...\0\0" -> UTF-8, same layout
    if (const wchar_t* f = p->lpstrFilter)
    {
        while (*f) { const std::wstring Part = f; Filter += xlion_win32_shim::ToUtf8(Part.c_str()); Filter += '\0'; f += Part.size() + 1; }
    }
    Filter += '\0';
    std::string Initial = xlion_win32_shim::ToUtf8(p->lpstrFile);          // a file name already in the buffer is the suggestion
    if (const std::string Dir = xlion_win32_shim::ToUtf8(p->lpstrInitialDir); !Dir.empty())
        Initial = Initial.empty() ? Dir + "/" : (Initial.find('/') == std::string::npos && Initial.find('\\') == std::string::npos ? Dir + "/" + Initial : Initial);
    char Out[4096] = {};
    if (!xlion_gui_FileDialog(Mode, p->lpstrTitle ? xlion_win32_shim::ToUtf8(p->lpstrTitle).c_str() : nullptr, Initial.c_str(),
                              p->lpstrFilter ? Filter.data() : nullptr, Out, static_cast<int>(sizeof(Out)))) return FALSE;
    const std::wstring W = xlion_win32_shim::FromUtf8(Out);
    if (W.size() + 1 > p->nMaxFile) return FALSE;
    std::wmemcpy(p->lpstrFile, W.c_str(), W.size() + 1);
    const auto Slash = W.find_last_of(L'/');
    const auto Dot   = W.find_last_of(L'.');
    p->nFileOffset    = static_cast<WORD>(Slash == std::wstring::npos ? 0 : Slash + 1);
    p->nFileExtension = static_cast<WORD>((Dot == std::wstring::npos || (Slash != std::wstring::npos && Dot < Slash)) ? W.size() : Dot + 1);
    return TRUE;
}
inline BOOL GetOpenFileNameW( OPENFILENAMEW* p ) noexcept { return ShimFileDialog(p, 0); }
inline BOOL GetSaveFileNameW( OPENFILENAMEW* p ) noexcept { return ShimFileDialog(p, 1); }
// ---------------------------------------------------------------------------------
// round 3: dynamic libraries - a REAL implementation on top of dlopen/dlsym/dlclose.
// Module names keep their Windows spelling at the call sites ("LIONCore.dll"); here
// "Name.dll" maps to "libName.so", looked up next to the executable first, then on
// the normal loader path. Paths with a directory keep the directory.
// ---------------------------------------------------------------------------------
#include <dlfcn.h>
#include <link.h>
#include <climits>
#include <string>
#include <filesystem>

namespace xlion_win32_shim
{
    inline std::string Narrow( LPCWSTR p ) { return p ? std::filesystem::path(p).string() : std::string{}; }
    inline std::string Narrow( LPCSTR  p ) { return p ? std::string(p) : std::string{}; }

    inline std::string ExeDir( void )
    {
        char Buf[PATH_MAX]{};
        const auto n = ::readlink("/proc/self/exe", Buf, sizeof(Buf) - 1);
        if (n <= 0) return {};
        return std::filesystem::path(std::string(Buf, static_cast<std::size_t>(n))).parent_path().string();
    }

    // "Dir/Name.dll" -> candidates { "Dir/libName.so", "Dir/Name.so", original }
    inline void* Open( const std::string& Name, int Flags )
    {
        if (Name.empty()) return ::dlopen(nullptr, Flags);
        std::filesystem::path P(Name);
        std::string Ext = P.extension().string();
        for (auto& c : Ext) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        std::vector<std::string> Candidates;
        if (Ext == ".dll")
        {
            const auto Stem = P.stem().string();
            const auto Dir  = P.parent_path();
            if (Dir.empty())
            {
                const auto Exe = ExeDir();
                if (!Exe.empty()) { Candidates.push_back(Exe + "/lib" + Stem + ".so"); Candidates.push_back(Exe + "/" + Stem + ".so"); }
                Candidates.push_back("lib" + Stem + ".so");
            }
            else
            {
                Candidates.push_back((Dir / ("lib" + Stem + ".so")).string());
                Candidates.push_back((Dir / (Stem + ".so")).string());
            }
        }
        Candidates.push_back(Name);
        for (auto& C : Candidates) if (void* h = ::dlopen(C.c_str(), Flags)) return h;
        return nullptr;
    }
}

#define LOAD_WITH_ALTERED_SEARCH_PATH     0x00000008
#define LOAD_LIBRARY_SEARCH_DEFAULT_DIRS  0x00001000
typedef long long (*FARPROC)();
inline HMODULE LoadLibraryW  ( LPCWSTR p )               noexcept { return reinterpret_cast<HMODULE>(xlion_win32_shim::Open(xlion_win32_shim::Narrow(p), RTLD_NOW | RTLD_LOCAL)); }
inline HMODULE LoadLibraryA  ( LPCSTR  p )               noexcept { return reinterpret_cast<HMODULE>(xlion_win32_shim::Open(xlion_win32_shim::Narrow(p), RTLD_NOW | RTLD_LOCAL)); }
template< typename C >
inline HMODULE LoadLibraryExW( const C* p, HANDLE, DWORD ) noexcept { return reinterpret_cast<HMODULE>(xlion_win32_shim::Open(xlion_win32_shim::Narrow(p), RTLD_NOW | RTLD_LOCAL)); }
#define LoadLibrary LoadLibraryW
// GetModuleHandle: only modules that are already loaded (RTLD_NOLOAD); null name = the program
template< typename C >
inline HMODULE GetModuleHandleW_impl( const C* p ) noexcept { return reinterpret_cast<HMODULE>(xlion_win32_shim::Open(p ? xlion_win32_shim::Narrow(p) : std::string{}, RTLD_NOW | RTLD_NOLOAD)); }
#undef GetModuleHandle
#define GetModuleHandleW(p) GetModuleHandleW_impl(p)
#define GetModuleHandleA(p) GetModuleHandleW_impl(p)
#define GetModuleHandle(p)  GetModuleHandleW_impl(p)
inline FARPROC GetProcAddress( HMODULE h, LPCSTR pName ) noexcept { return h ? reinterpret_cast<FARPROC>(::dlsym(reinterpret_cast<void*>(h), pName)) : nullptr; }
inline BOOL    FreeLibrary   ( HMODULE h )               noexcept { return h && ::dlclose(reinterpret_cast<void*>(h)) == 0; }
inline std::string GetModuleFileName_impl( HMODULE h )
{
    if (!h) { const auto Exe = xlion_win32_shim::ExeDir(); char Buf[PATH_MAX]{}; const auto n = ::readlink("/proc/self/exe", Buf, sizeof(Buf) - 1); return n > 0 ? std::string(Buf, static_cast<std::size_t>(n)) : std::string{}; }
    struct link_map* pMap = nullptr;
    if (::dlinfo(reinterpret_cast<void*>(h), RTLD_DI_LINKMAP, &pMap) != 0 || !pMap || !pMap->l_name || !pMap->l_name[0]) return GetModuleFileName_impl(nullptr);
    return pMap->l_name;
}
#undef GetModuleFileName
#define GetModuleFileNameW(h, b, n) GetModuleFileNameW_impl(h, b, n)
#define GetModuleFileNameA(h, b, n) GetModuleFileNameA_impl(h, b, n)
#define GetModuleFileName(h, b, n)  GetModuleFileNameW_impl(h, b, n)
inline DWORD GetModuleFileNameW_impl( HMODULE h, LPWSTR b, DWORD n ) noexcept
{
    if (!b || !n) return 0;
    const std::wstring W = std::filesystem::path(GetModuleFileName_impl(h)).wstring();
    const auto c = std::min<std::size_t>(W.size(), n - 1);
    std::wmemcpy(b, W.data(), c); b[c] = 0; return static_cast<DWORD>(c);
}
inline DWORD GetModuleFileNameA_impl( HMODULE h, LPSTR b, DWORD n ) noexcept
{
    if (!b || !n) return 0;
    const std::string S = GetModuleFileName_impl(h);
    const auto c = std::min<std::size_t>(S.size(), n - 1);
    std::memcpy(b, S.data(), c); b[c] = 0; return static_cast<DWORD>(c);
}

// ---------------------------------------------------------------------------------
// round 3: misc types/constants and failing stubs
// ---------------------------------------------------------------------------------
typedef wchar_t       TCHAR;
typedef const wchar_t* PCWSTR;
typedef wchar_t*      PWSTR;
typedef DWORD*        PDWORD;
typedef void*         PVOID;
typedef ULONG*        PULONG;
#define MONITORINFOF_PRIMARY            0x00000001
#define ERROR_SHARING_VIOLATION         32L
#define EXCEPTION_ACCESS_VIOLATION      0xC0000005u
#define EXCEPTION_BREAKPOINT            0x80000003u
#define EXCEPTION_STACK_OVERFLOW        0xC00000FDu
#define EXCEPTION_EXECUTE_HANDLER       1
#define EXCEPTION_CONTINUE_SEARCH       0
// Job objects (child process groups): xlion_win32_kernel.h
struct JOBOBJECT_BASIC_LIMIT_INFORMATION { LONGLONG PerProcessUserTimeLimit, PerJobUserTimeLimit; DWORD LimitFlags; SIZE_T MinimumWorkingSetSize, MaximumWorkingSetSize; DWORD ActiveProcessLimit; ULONG_PTR Affinity; DWORD PriorityClass, SchedulingClass; };
struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION { JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation; ULONGLONG IoInfo[6]; SIZE_T ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed; };
enum JOBOBJECTINFOCLASS { JobObjectExtendedLimitInformation = 9 };
#define JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE 0x00002000
// Named pipes: not used on Linux (the command console uses a Unix domain socket instead)
#define PIPE_ACCESS_INBOUND            0x00000001
#define PIPE_ACCESS_OUTBOUND           0x00000002
#define PIPE_ACCESS_DUPLEX             0x00000003
#define FILE_FLAG_FIRST_PIPE_INSTANCE  0x00080000
#define PIPE_TYPE_BYTE                 0x00000000
#define PIPE_TYPE_MESSAGE              0x00000004
#define PIPE_READMODE_BYTE             0x00000000
#define PIPE_READMODE_MESSAGE          0x00000002
#define PIPE_WAIT                      0x00000000
#define PIPE_NOWAIT                    0x00000001
#define PIPE_REJECT_REMOTE_CLIENTS     0x00000008
#define PIPE_UNLIMITED_INSTANCES       255
#define NMPWAIT_WAIT_FOREVER           0xffffffff
inline HANDLE CreateNamedPipeA( LPCSTR,  DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, LPSECURITY_ATTRIBUTES ) noexcept { return INVALID_HANDLE_VALUE; }
inline HANDLE CreateNamedPipeW( LPCWSTR, DWORD, DWORD, DWORD, DWORD, DWORD, DWORD, LPSECURITY_ATTRIBUTES ) noexcept { return INVALID_HANDLE_VALUE; }
inline BOOL   ConnectNamedPipe( HANDLE, LPOVERLAPPED ) noexcept { return FALSE; }
inline BOOL   DisconnectNamedPipe( HANDLE ) noexcept { return FALSE; }
inline BOOL   WaitNamedPipeA( LPCSTR, DWORD ) noexcept { return FALSE; }
inline BOOL   SetNamedPipeHandleState( HANDLE, LPDWORD, LPDWORD, LPDWORD ) noexcept { return FALSE; }
// ---------------------------------------------------------------------------------
// round 4
// ---------------------------------------------------------------------------------
#define OFN_EXPLORER        0x00080000
#define OFN_HIDEREADONLY    0x00000004
#define OFN_ENABLESIZING    0x00800000
template< typename A, typename B, typename C, typename D, typename E >
inline HINSTANCE ShellExecuteW( HWND, A, B pFile, C pParams, D pDir, E ) noexcept
{
    const bool bOk = xlion_gui_ShellOpen && xlion_gui_ShellOpen(xlion_win32_shim::ToUtf8(pFile).c_str(), xlion_win32_shim::ToUtf8(pParams).c_str(), xlion_win32_shim::ToUtf8(pDir).c_str());
    return reinterpret_cast<HINSTANCE>(static_cast<std::intptr_t>(bOk ? 42 : 2));
}
struct OPENASINFO { LPCWSTR pcszFile; LPCWSTR pcszClass; int oaifInFlags; };
#define OAIF_ALLOW_REGISTRATION 0x00000001
#define OAIF_REGISTER_EXT       0x00000002
#define OAIF_EXEC               0x00000004
// No "Open with" chooser on Linux desktops in general: the file goes to its default application
inline HRESULT SHOpenWithDialog( HWND, const OPENASINFO* p ) noexcept
{
    return (p && xlion_gui_ShellOpen && xlion_gui_ShellOpen(xlion_win32_shim::ToUtf8(p->pcszFile).c_str(), nullptr, nullptr)) ? S_OK : E_FAIL;
}
// CommandLineToArgvW: the real arguments of this process (from /proc/self/cmdline); the string passed in is
// ignored (GetCommandLineW has nothing to give on Linux). One block, freed with LocalFree like on Windows.
inline LPWSTR* CommandLineToArgvW( LPCWSTR, int* pArgc ) noexcept
{
    if (pArgc) *pArgc = 0;
    std::vector<std::wstring> Args;
    if (FILE* f = std::fopen("/proc/self/cmdline", "rb"))
    {
        std::string Cur; int c;
        while ((c = std::fgetc(f)) != EOF)
        {
            if (c == 0) { Args.push_back(std::filesystem::path(Cur).wstring()); Cur.clear(); }
            else Cur.push_back(static_cast<char>(c));
        }
        if (!Cur.empty()) Args.push_back(std::filesystem::path(Cur).wstring());
        std::fclose(f);
    }
    std::size_t Bytes = (Args.size() + 1) * sizeof(LPWSTR);
    for (auto& A : Args) Bytes += (A.size() + 1) * sizeof(wchar_t);
    auto* pBlock = static_cast<LPWSTR*>(std::malloc(Bytes));
    if (!pBlock) return nullptr;
    auto* pText = reinterpret_cast<wchar_t*>(pBlock + Args.size() + 1);
    for (std::size_t i = 0; i < Args.size(); ++i)
    {
        pBlock[i] = pText;
        std::wmemcpy(pText, Args[i].c_str(), Args[i].size() + 1);
        pText += Args[i].size() + 1;
    }
    pBlock[Args.size()] = nullptr;
    if (pArgc) *pArgc = static_cast<int>(Args.size());
    return pBlock;
}
// ---------------------------------------------------------------------------------
// round 5: COM init / misc
// ---------------------------------------------------------------------------------
#define COINIT_APARTMENTTHREADED  0x2
#define COINIT_MULTITHREADED      0x0
#define COINIT_DISABLE_OLE1DDE    0x4
#define OAIF_HIDE_REGISTRATION    0x00000020
#define OAIF_URL_PROTOCOL         0x00000040
#define ERROR_CANCELLED           1223L
inline HRESULT CoInitializeEx( LPVOID, DWORD ) noexcept { return E_FAIL; }
inline HRESULT CoInitialize( LPVOID ) noexcept { return E_FAIL; }
inline void    CoUninitialize( void ) noexcept {}
inline BOOL    PtInRect( const RECT* r, POINT p ) noexcept { return r && p.x >= r->left && p.x < r->right && p.y >= r->top && p.y < r->bottom; }
inline HRESULT HRESULT_FROM_WIN32( unsigned long x ) noexcept { return (HRESULT)(x) <= 0 ? (HRESULT)(x) : (HRESULT)(((x) & 0x0000FFFF) | (7 << 16) | 0x80000000); }

// ---------------------------------------------------------------------------------
// the kernel objects headless really uses (files, directory watching, pipes, processes, jobs)
// ---------------------------------------------------------------------------------
#include "xlion_win32_kernel.h"
