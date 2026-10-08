// xlion_platform_compat_linux.h - Linux (non-MSVC) compatibility shim for the xLION depots.
//
// Force-included (-include) into every C++ translation unit of the Linux build ONLY (see the
// "Linux port" block near the top of xLION/CMakeLists.txt). Never seen by MSVC, so the Windows build
// is unaffected. It supplies:
//   1. the standard headers MSVC's STL pulls in transitively (code here relies on that a lot), and
//   2. the subset of the MSVC "secure CRT" / Win32 CRT names the depots use (strcpy_s, sprintf_s,
//      _aligned_malloc, errno_t, ...), with the same semantics (always NUL terminated, truncating).
// Proper per-depot fixes can replace entries here over time; keep this file the only place they live.
#pragma once
#if !defined(_WIN32)

#ifdef __cplusplus
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cwchar>
#include <cwctype>
#include <cctype>
#include <cerrno>
#include <cmath>
#include <cassert>
#include <climits>
#include <cfloat>
#include <ctime>
#include <cstdarg>
#include <new>
#include <memory>
#include <utility>
#include <type_traits>
#include <limits>
#include <algorithm>
#include <functional>
#include <string>
#include <string_view>
#include <vector>
#include <array>
#include <span>
#include <atomic>
#include <mutex>
#include <thread>
#include <chrono>
#include <iterator>
#include <tuple>
#include <optional>
#include <variant>
#include <initializer_list>
#include <bit>
#include <numeric>
#include <format>
#include <unordered_map>
#include <map>
#include <set>
#include <unordered_set>
#include <filesystem>
#include <sstream>
#include <fstream>
#include <iostream>
#include <random>
#include <condition_variable>
#include <shared_mutex>
#endif
#if defined(__x86_64__) || defined(__i386__)
#include <immintrin.h>   // MSVC's <intrin.h>/<xmmintrin.h> chain exposes every ISA's intrinsics; clang's does not
#endif
#include <strings.h>
#include <unistd.h>
#include <malloc.h>
#include <sys/stat.h>

#ifdef __cplusplus
// libstdc++ 13 does not declare the float-suffixed <cmath> functions in std:: (the standard and MSVC do).
#if defined(__GLIBCXX__)
namespace std
{
    using ::sqrtf; using ::sinf; using ::cosf; using ::tanf; using ::asinf; using ::acosf; using ::atanf;
    using ::atan2f; using ::fabsf; using ::fmodf; using ::powf; using ::expf; using ::logf; using ::log2f;
    using ::log10f; using ::floorf; using ::ceilf; using ::roundf; using ::truncf; using ::hypotf;
    using ::copysignf; using ::fminf; using ::fmaxf; using ::exp2f; using ::cbrtf; using ::sinhf; using ::coshf; using ::tanhf;
}
#endif
#endif

#ifndef _TRUNCATE
#define _TRUNCATE ((size_t)-1)
#endif
typedef int errno_t;

#ifndef __forceinline
#define __forceinline inline __attribute__((always_inline))
#endif
#ifndef _countof
#define _countof(a) (sizeof(a) / sizeof((a)[0]))
#endif
#ifndef MAX_PATH
#define MAX_PATH 260
#endif

#ifdef __cplusplus
namespace xlion_compat
{
    inline errno_t strncpy_impl(char* pDst, size_t DstSize, const char* pSrc, size_t Count) noexcept
    {
        if (!pDst || DstSize == 0) return EINVAL;
        if (!pSrc) { pDst[0] = 0; return EINVAL; }
        size_t n = 0;
        const size_t Max = (Count == _TRUNCATE) ? DstSize - 1 : (Count < DstSize - 1 ? Count : DstSize - 1);
        while (n < Max && pSrc[n]) { pDst[n] = pSrc[n]; ++n; }
        pDst[n] = 0;
        return (Count != _TRUNCATE && pSrc[n] && n < Count) ? ERANGE : 0;
    }
    inline errno_t wcsncpy_impl(wchar_t* pDst, size_t DstSize, const wchar_t* pSrc, size_t Count) noexcept
    {
        if (!pDst || DstSize == 0) return EINVAL;
        if (!pSrc) { pDst[0] = 0; return EINVAL; }
        size_t n = 0;
        const size_t Max = (Count == _TRUNCATE) ? DstSize - 1 : (Count < DstSize - 1 ? Count : DstSize - 1);
        while (n < Max && pSrc[n]) { pDst[n] = pSrc[n]; ++n; }
        pDst[n] = 0;
        return 0;
    }
}

inline errno_t strcpy_s(char* pDst, size_t DstSize, const char* pSrc) noexcept { return xlion_compat::strncpy_impl(pDst, DstSize, pSrc, _TRUNCATE); }
template<size_t N> inline errno_t strcpy_s(char (&Dst)[N], const char* pSrc) noexcept { return strcpy_s(Dst, N, pSrc); }
inline errno_t strncpy_s(char* pDst, size_t DstSize, const char* pSrc, size_t Count) noexcept { return xlion_compat::strncpy_impl(pDst, DstSize, pSrc, Count); }
template<size_t N> inline errno_t strncpy_s(char (&Dst)[N], const char* pSrc, size_t Count) noexcept { return strncpy_s(Dst, N, pSrc, Count); }
inline errno_t strcat_s(char* pDst, size_t DstSize, const char* pSrc) noexcept
{
    if (!pDst || DstSize == 0) return EINVAL;
    const size_t L = strnlen(pDst, DstSize);
    return xlion_compat::strncpy_impl(pDst + L, DstSize - L, pSrc, _TRUNCATE);
}
template<size_t N> inline errno_t strcat_s(char (&Dst)[N], const char* pSrc) noexcept { return strcat_s(Dst, N, pSrc); }
inline errno_t wcscpy_s(wchar_t* pDst, size_t DstSize, const wchar_t* pSrc) noexcept { return xlion_compat::wcsncpy_impl(pDst, DstSize, pSrc, _TRUNCATE); }
template<size_t N> inline errno_t wcscpy_s(wchar_t (&Dst)[N], const wchar_t* pSrc) noexcept { return wcscpy_s(Dst, N, pSrc); }
inline errno_t wcsncpy_s(wchar_t* pDst, size_t DstSize, const wchar_t* pSrc, size_t Count) noexcept { return xlion_compat::wcsncpy_impl(pDst, DstSize, pSrc, Count); }
inline errno_t memcpy_s(void* pDst, size_t DstSize, const void* pSrc, size_t Count) noexcept
{
    if (Count == 0) return 0;
    if (!pDst || !pSrc) return EINVAL;
    if (Count > DstSize) { std::memset(pDst, 0, DstSize); return ERANGE; }
    std::memcpy(pDst, pSrc, Count); return 0;
}
inline errno_t memmove_s(void* pDst, size_t DstSize, const void* pSrc, size_t Count) noexcept
{
    if (Count == 0) return 0;
    if (!pDst || !pSrc) return EINVAL;
    if (Count > DstSize) return ERANGE;
    std::memmove(pDst, pSrc, Count); return 0;
}

// sprintf_s / _snprintf_s / vsprintf_s: always NUL terminated (MSVC's sprintf_s calls the invalid
// parameter handler on overflow; truncating is the safe equivalent here).
inline int vsprintf_s(char* pDst, size_t DstSize, const char* pFmt, va_list Args) noexcept { return std::vsnprintf(pDst, DstSize, pFmt, Args); }
template<size_t N> inline int vsprintf_s(char (&Dst)[N], const char* pFmt, va_list Args) noexcept { return std::vsnprintf(Dst, N, pFmt, Args); }
inline int sprintf_s(char* pDst, size_t DstSize, const char* pFmt, ...) noexcept { va_list a; va_start(a, pFmt); int r = std::vsnprintf(pDst, DstSize, pFmt, a); va_end(a); return r; }
template<size_t N> inline int sprintf_s(char (&Dst)[N], const char* pFmt, ...) noexcept { va_list a; va_start(a, pFmt); int r = std::vsnprintf(Dst, N, pFmt, a); va_end(a); return r; }
inline int _snprintf_s(char* pDst, size_t DstSize, size_t /*Count*/, const char* pFmt, ...) noexcept { va_list a; va_start(a, pFmt); int r = std::vsnprintf(pDst, DstSize, pFmt, a); va_end(a); return r; }
inline int _vsnprintf_s(char* pDst, size_t DstSize, size_t /*Count*/, const char* pFmt, va_list a) noexcept { return std::vsnprintf(pDst, DstSize, pFmt, a); }
inline int vsnprintf_s(char* pDst, size_t DstSize, size_t /*Count*/, const char* pFmt, va_list a) noexcept { return std::vsnprintf(pDst, DstSize, pFmt, a); }
inline int swprintf_s(wchar_t* pDst, size_t DstSize, const wchar_t* pFmt, ...) noexcept { va_list a; va_start(a, pFmt); int r = std::vswprintf(pDst, DstSize, pFmt, a); va_end(a); return r; }
template<size_t N> inline int swprintf_s(wchar_t (&Dst)[N], const wchar_t* pFmt, ...) noexcept { va_list a; va_start(a, pFmt); int r = std::vswprintf(Dst, N, pFmt, a); va_end(a); return r; }
#define _snprintf  snprintf
#define _vsnprintf vsnprintf
#define sscanf_s   sscanf
#define swscanf_s  swscanf

inline errno_t wcstombs_s(size_t* pRet, char* pDst, size_t DstSize, const wchar_t* pSrc, size_t Count) noexcept
{
    const size_t Max = pDst ? ((Count == _TRUNCATE || Count >= DstSize) ? DstSize - 1 : Count) : 0;
    const size_t n   = std::wcstombs(pDst, pSrc, pDst ? Max : 0);
    if (n == static_cast<size_t>(-1)) { if (pDst && DstSize) pDst[0] = 0; if (pRet) *pRet = 0; return EILSEQ; }
    if (pDst) pDst[n < Max ? n : Max] = 0;
    if (pRet) *pRet = n + 1;
    return 0;
}
inline errno_t mbstowcs_s(size_t* pRet, wchar_t* pDst, size_t DstSize, const char* pSrc, size_t Count) noexcept
{
    const size_t Max = pDst ? ((Count == _TRUNCATE || Count >= DstSize) ? DstSize - 1 : Count) : 0;
    const size_t n   = std::mbstowcs(pDst, pSrc, pDst ? Max : 0);
    if (n == static_cast<size_t>(-1)) { if (pDst && DstSize) pDst[0] = 0; if (pRet) *pRet = 0; return EILSEQ; }
    if (pDst) pDst[n < Max ? n : Max] = 0;
    if (pRet) *pRet = n + 1;
    return 0;
}

// Wide-path CRT file functions: POSIX file names are bytes, the depots' wide paths are converted to UTF-8.
inline std::string xlion_compat_utf8(const wchar_t* p) { return std::filesystem::path(std::wstring(p ? p : L"")).string(); }
inline FILE* _wfopen(const wchar_t* pName, const wchar_t* pMode) noexcept
{
    try { return std::fopen(xlion_compat_utf8(pName).c_str(), xlion_compat_utf8(pMode).c_str()); } catch (...) { errno = EINVAL; return nullptr; }
}
inline errno_t _wfopen_s(FILE** ppF, const wchar_t* pName, const wchar_t* pMode) noexcept
{
    *ppF = _wfopen(pName, pMode); return *ppF ? 0 : errno;
}
inline errno_t _wcserror_s(wchar_t* pBuf, size_t Size, int ErrNum) noexcept
{
    if (!pBuf || !Size) return EINVAL;
    std::mbstowcs(pBuf, std::strerror(ErrNum), Size - 1); pBuf[Size - 1] = 0; return 0;
}
template<size_t N> inline errno_t _wcserror_s(wchar_t (&Buf)[N], int ErrNum) noexcept { return _wcserror_s(Buf, N, ErrNum); }
inline int _wremove(const wchar_t* p) noexcept { return std::remove(xlion_compat_utf8(p).c_str()); }
inline int _wrename(const wchar_t* a, const wchar_t* b) noexcept { return std::rename(xlion_compat_utf8(a).c_str(), xlion_compat_utf8(b).c_str()); }

inline int _stricmp(const char* a, const char* b) noexcept { return strcasecmp(a, b); }
inline int _strnicmp(const char* a, const char* b, size_t n) noexcept { return strncasecmp(a, b, n); }
inline int _wcsicmp(const wchar_t* a, const wchar_t* b) noexcept { return wcscasecmp(a, b); }
inline int _wcsnicmp(const wchar_t* a, const wchar_t* b, size_t n) noexcept { return wcsncasecmp(a, b, n); }
inline errno_t localtime_s(std::tm* pOut, const std::time_t* pT) noexcept { return localtime_r(pT, pOut) ? 0 : EINVAL; }
inline errno_t gmtime_s(std::tm* pOut, const std::time_t* pT) noexcept { return gmtime_r(pT, pOut) ? 0 : EINVAL; }
inline errno_t fopen_s(FILE** ppF, const char* pName, const char* pMode) noexcept { *ppF = std::fopen(pName, pMode); return *ppF ? 0 : errno; }
inline errno_t _dupenv_s(char** ppBuf, size_t* pLen, const char* pName) noexcept
{
    const char* p = std::getenv(pName);
    if (!p) { *ppBuf = nullptr; if (pLen) *pLen = 0; return 0; }
    *ppBuf = strdup(p); if (pLen) *pLen = std::strlen(p) + 1; return 0;
}

inline void* _aligned_malloc(size_t Size, size_t Align) noexcept
{
    if (Align < sizeof(void*)) Align = sizeof(void*);
    void* p = nullptr;
    return posix_memalign(&p, Align, Size ? Size : 1) == 0 ? p : nullptr;
}
inline void  _aligned_free(void* p) noexcept { std::free(p); }
inline void* _aligned_realloc(void* p, size_t Size, size_t Align) noexcept
{
    void* n = _aligned_malloc(Size, Align);
    if (n && p) { std::memcpy(n, p, std::min(Size, malloc_usable_size(p))); std::free(p); }
    return n;
}
#define _alloca alloca

#define __debugbreak() __builtin_debugtrap()

//------------------------------------------------------------------------------------------------
// Win32 virtual memory (VirtualAlloc/VirtualFree) on mmap - xECSV2's pools reserve a big address
// range once and commit pages on demand, exactly the reserve/commit model below.
//------------------------------------------------------------------------------------------------
#include <sys/mman.h>
#ifndef MEM_COMMIT
#define MEM_COMMIT      0x00001000u
#define MEM_RESERVE     0x00002000u
#define MEM_DECOMMIT    0x00004000u
#define MEM_RELEASE     0x00008000u
#define PAGE_NOACCESS   0x01u
#define PAGE_READONLY   0x02u
#define PAGE_READWRITE  0x04u
#endif
namespace xlion_compat
{
    struct vmem_registry   // reservation base -> size (munmap needs the size, VirtualFree(MEM_RELEASE) gets 0)
    {
        std::mutex                          m_Lock;
        std::unordered_map<void*, size_t>   m_Sizes;
        static vmem_registry& get() noexcept { static vmem_registry s; return s; }
    };
    inline int ToProt(unsigned Protect) noexcept
    {
        return (Protect & PAGE_READWRITE) ? (PROT_READ | PROT_WRITE) : (Protect & PAGE_READONLY) ? PROT_READ : PROT_NONE;
    }
}
inline void* VirtualAlloc(void* pAddress, size_t Size, unsigned AllocationType, unsigned Protect) noexcept
{
    if (pAddress == nullptr || (AllocationType & MEM_RESERVE))
    {
        // Reserve (optionally commit) a new range
        const int Prot = (AllocationType & MEM_COMMIT) ? xlion_compat::ToProt(Protect) : PROT_NONE;
        void* p = mmap(pAddress, Size, Prot, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);
        if (p == MAP_FAILED) return nullptr;
        auto& R = xlion_compat::vmem_registry::get();
        std::lock_guard Lk(R.m_Lock);
        R.m_Sizes[p] = Size;
        return p;
    }
    // Commit pages inside an existing reservation
    return mprotect(pAddress, Size, xlion_compat::ToProt(Protect)) == 0 ? pAddress : nullptr;
}
inline int VirtualFree(void* pAddress, size_t Size, unsigned FreeType) noexcept
{
    if (FreeType & MEM_RELEASE)
    {
        auto& R = xlion_compat::vmem_registry::get();
        size_t Len = 0;
        {
            std::lock_guard Lk(R.m_Lock);
            auto It = R.m_Sizes.find(pAddress);
            if (It == R.m_Sizes.end()) return 0;
            Len = It->second; R.m_Sizes.erase(It);
        }
        return munmap(pAddress, Len) == 0;
    }
    // MEM_DECOMMIT: give the pages back, keep the address range reserved
    madvise(pAddress, Size, MADV_DONTNEED);
    return mprotect(pAddress, Size, PROT_NONE) == 0;
}
#endif // __cplusplus
// strerror_s (MSVC CRT) on top of the thread-safe GNU strerror_r
inline errno_t strerror_s( char* pBuf, std::size_t Size, int Err ) noexcept
{
    if (!pBuf || !Size) return EINVAL;
    const char* p = ::strerror_r(Err, pBuf, Size);
    if (p != pBuf) { std::strncpy(pBuf, p, Size - 1); pBuf[Size - 1] = 0; }
    return 0;
}
template< std::size_t N > inline errno_t strerror_s( char (&Buf)[N], int Err ) noexcept { return strerror_s(Buf, N, Err); }

// _wdupenv_s / getenv_s / _popen / _pclose
inline errno_t _wdupenv_s( wchar_t** ppValue, std::size_t* pLen, const wchar_t* pName ) noexcept
{
    if (!ppValue) return EINVAL;
    *ppValue = nullptr; if (pLen) *pLen = 0;
    const char* p = std::getenv(std::filesystem::path(pName).string().c_str());
    if (!p) return 0;
    const std::wstring W = std::filesystem::path(p).wstring();
    *ppValue = static_cast<wchar_t*>(std::malloc((W.size() + 1) * sizeof(wchar_t)));
    if (!*ppValue) return ENOMEM;
    std::wmemcpy(*ppValue, W.c_str(), W.size() + 1);
    if (pLen) *pLen = W.size() + 1;
    return 0;
}
inline errno_t getenv_s( std::size_t* pLen, char* pBuf, std::size_t Size, const char* pName ) noexcept
{
    if (pLen) *pLen = 0;
    if (pBuf && Size) pBuf[0] = 0;
    const char* p = std::getenv(pName);
    if (!p) return 0;
    const std::size_t n = std::strlen(p) + 1;
    if (pLen) *pLen = n;
    if (!pBuf || Size < n) return pBuf ? ERANGE : 0;
    std::memcpy(pBuf, p, n);
    return 0;
}
#define _popen  popen
#define _pclose pclose

// array-size overloads of the secure CRT (MSVC provides these as templates)
template< std::size_t N > inline errno_t wcsncpy_s(wchar_t (&Dst)[N], const wchar_t* pSrc, std::size_t Count) noexcept { return wcsncpy_s(Dst, N, pSrc, Count); }

#endif // !_WIN32