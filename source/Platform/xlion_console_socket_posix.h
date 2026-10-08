#ifndef XLION_CONSOLE_SOCKET_POSIX_H
#define XLION_CONSOLE_SOCKET_POSIX_H
#pragma once
//
// Linux port (linux-headless branch): the Command Console transport on POSIX.
//
// Windows uses the named pipe \\.\pipe\xEditor_Console. Here the same protocol runs over a Unix domain
// stream socket: the client connects, sends ONE command ended by a line break (outside quotes), and reads
// the reply until the server closes the connection. One client at a time, exactly like the pipe.
//
// Socket path: $XEDITOR_PIPE when it is set (the same variable the Windows tools use to name another
// pipe), else /tmp/xEditor_Console.sock. Used by the editor (LevelEditor_CommandConsolePipe.h) and by
// xeditorcli, so both always agree.
//
#if defined(_WIN32)
#error "POSIX only"
#endif
#include <sys/socket.h>
#include <sys/un.h>
#include <poll.h>
#include <unistd.h>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <string>

namespace xlion::console_socket
{
    inline std::string Path( void ) noexcept
    {
        if (const char* p = std::getenv("XEDITOR_PIPE"); p && *p) return p;
        return "/tmp/xEditor_Console.sock";
    }

    inline bool FillAddress( const std::string& P, sockaddr_un& Addr ) noexcept
    {
        std::memset(&Addr, 0, sizeof(Addr));
        Addr.sun_family = AF_UNIX;
        if (P.size() >= sizeof(Addr.sun_path)) return false;
        std::memcpy(Addr.sun_path, P.c_str(), P.size() + 1);
        return true;
    }

    // Server: a listening socket at P (a stale file from a crashed run is replaced). -1 on failure.
    inline int Listen( const std::string& P ) noexcept
    {
        sockaddr_un Addr;
        if (!FillAddress(P, Addr)) return -1;
        const int Fd = ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
        if (Fd < 0) return -1;
        ::unlink(P.c_str());
        if (::bind(Fd, reinterpret_cast<const sockaddr*>(&Addr), sizeof(Addr)) != 0 || ::listen(Fd, 4) != 0) { ::close(Fd); return -1; }
        return Fd;
    }

    // Client: connected socket, -1 on failure (errno says why).
    inline int Connect( const std::string& P ) noexcept
    {
        sockaddr_un Addr;
        if (!FillAddress(P, Addr)) { errno = ENAMETOOLONG; return -1; }
        const int Fd = ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
        if (Fd < 0) return -1;
        if (::connect(Fd, reinterpret_cast<const sockaddr*>(&Addr), sizeof(Addr)) != 0) { const int e = errno; ::close(Fd); errno = e; return -1; }
        return Fd;
    }

    inline bool WriteAll( int Fd, const char* p, std::size_t n ) noexcept
    {
        while (n)
        {
            const ssize_t w = ::send(Fd, p, n, MSG_NOSIGNAL);
            if (w < 0) { if (errno == EINTR) continue; return false; }
            p += w; n -= static_cast<std::size_t>(w);
        }
        return true;
    }

    // Read some bytes; 0 = closed, -1 = error
    inline ssize_t ReadSome( int Fd, char* p, std::size_t n ) noexcept
    {
        for (;;) { const ssize_t r = ::recv(Fd, p, n, 0); if (r < 0 && errno == EINTR) continue; return r; }
    }

    // Whether bytes are waiting (PeekNamedPipe's job on Windows), waiting at most Ms milliseconds
    inline bool HasData( int Fd, int Ms ) noexcept
    {
        pollfd P{ Fd, POLLIN, 0 };
        return ::poll(&P, 1, Ms) > 0 && (P.revents & POLLIN);
    }
}

#endif