// xeditorcli - generic CLI client for xeditor::ConsolePipeThreadMain. One-shot connect / send / read / exit, zero dependency on the rest of xGPU, just Win32.
//
// Usage:   xeditorcli <command line>
//
// Everything after the program name is sent to the editor exactly as it was typed - the raw command line, not argv: by the time main() runs the C runtime has already removed
// quotes and processed backslashes, and a tool that rebuilds the command from argv can only guess what the person meant. The editor parses the line itself, with one set
// of rules (Windows command line rules: "quotes" keep spaces, tabs and line breaks, a backslash only matters in front of a quote), so a command means the same typed here,
// sent by a script, or run from the editor's own console:
//
//      xeditorcli LogViewSave -Name "my view" -Query "channel:game.* sev>=error"
//      xeditorcli LogAttach -Path "C:\captures\crash 1.dmp" -Event 12
//
// The pipe is \\.\pipe\xEditor_Console, or the one in the XEDITOR_PIPE environment variable (the editor started with a pipe of its own, as the tests do).
#include <windows.h>
#include <iostream>
#include <string>

namespace
{
    constexpr const char* kDefaultPipeName = "\\\\.\\pipe\\xEditor_Console";

    // The command line without the program name: the first word, quoted or not, ends at the first space or tab outside quotes (CommandLineToArgvW's rule for argv[0]).
    std::wstring ArgumentsOf(const wchar_t* pLine)
    {
        const wchar_t* p = pLine;
        bool bQuoted = false;
        while (*p && (bQuoted || (*p != L' ' && *p != L'\t')))
        {
            if (*p == L'"') bQuoted = !bQuoted;
            ++p;
        }
        while (*p == L' ' || *p == L'\t') ++p;
        std::wstring Rest = p;
        while (!Rest.empty() && (Rest.back() == L' ' || Rest.back() == L'\t' || Rest.back() == L'\r' || Rest.back() == L'\n')) Rest.pop_back();
        return Rest;
    }

    std::string Utf8(const std::wstring& Text)
    {
        if (Text.empty()) return {};
        const int Size = WideCharToMultiByte(CP_UTF8, 0, Text.data(), static_cast<int>(Text.size()), nullptr, 0, nullptr, nullptr);
        std::string Out(static_cast<std::size_t>(Size), '\0');
        WideCharToMultiByte(CP_UTF8, 0, Text.data(), static_cast<int>(Text.size()), Out.data(), Size, nullptr, nullptr);
        return Out;
    }
}

int main()
{
    std::string Command = Utf8(ArgumentsOf(GetCommandLineW()));
    if (Command.empty())
    {
        std::cerr << "Usage: xeditorcli <command line>      (sent to the editor exactly as typed; XEDITOR_PIPE names another pipe)\n";
        return 1;
    }

    std::string PipeName = kDefaultPipeName;
    if (char Env[512]; GetEnvironmentVariableA("XEDITOR_PIPE", Env, sizeof(Env)) > 0 && GetEnvironmentVariableA("XEDITOR_PIPE", Env, sizeof(Env)) < sizeof(Env)) PipeName = Env;

    // A few short retries: the server side accepts one connection at a time and immediately loops
    // for the next one between requests, so ERROR_PIPE_BUSY just means "mid-turnaround."
    HANDLE hPipe = INVALID_HANDLE_VALUE;
    for (int Attempt = 0; Attempt < 5; ++Attempt)
    {
        hPipe = CreateFileA(PipeName.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, 0, nullptr);
        if (hPipe != INVALID_HANDLE_VALUE) break;
        if (GetLastError() != ERROR_PIPE_BUSY) break;
        WaitNamedPipeA(PipeName.c_str(), 2000);
    }
    if (hPipe == INVALID_HANDLE_VALUE)
    {
        std::cerr << "Could not connect to pipe '" << PipeName << "' (GetLastError=" << GetLastError() << ")\n";
        return 2;
    }

    // The editor reads up to the first line break that is not inside quotes, so this one ends the command (a quoted value may hold line breaks of its own).
    Command += '\n';
    DWORD BytesWritten = 0;
    WriteFile(hPipe, Command.data(), static_cast<DWORD>(Command.size()), &BytesWritten, nullptr);

    std::string Response;
    char Buf[4096];
    DWORD BytesRead = 0;
    while (ReadFile(hPipe, Buf, sizeof(Buf), &BytesRead, nullptr) && BytesRead > 0)
        Response.append(Buf, BytesRead);

    CloseHandle(hPipe);
    std::cout << Response;
    return 0;
}
