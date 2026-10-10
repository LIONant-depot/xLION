#pragma once
// Linux stand-in for the Windows <io.h>: the low level file calls under their underscore names (the smoke programs redirect stdout to "NUL" while they time something).
// <unistd.h> is not included on purpose: it declares the POSIX link() function, which hides xecs' type "link" in the programs that include this. The three calls it
// would bring are declared here exactly as glibc does (a different exception specification would be an error).
#include <fcntl.h>
#include <cstring>

extern "C"
{
    int dup (int) noexcept;
    int dup2(int, int) noexcept;
    int close(int);
}

#ifndef _O_WRONLY
    #define _O_WRONLY   O_WRONLY
    #define _O_RDONLY   O_RDONLY
    #define _O_RDWR     O_RDWR
    #define _O_BINARY   0
    #define _O_TEXT     0
#endif

inline int _dup  (int Fd)                    noexcept { return dup(Fd); }
inline int _dup2 (int From, int To)          noexcept { return dup2(From, To) == To ? 0 : -1; }       // 0 on success, as the CRT's
inline int _close(int Fd)                    noexcept { return close(Fd); }
inline int _open (const char* pPath, int Flags, int Mode = 0644) noexcept { return open(std::strcmp(pPath, "NUL") == 0 ? "/dev/null" : pPath, Flags, Mode); }
inline int _setmode(int, int)                noexcept { return 0; }
