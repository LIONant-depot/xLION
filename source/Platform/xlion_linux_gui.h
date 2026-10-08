#pragma once
//
// Linux port: the desktop services of the graphical editor (xLION) on X11 - the parts Win32 gives the Windows build for free.
// Only compiled into xLION on Linux (source/Platform/xlion_linux_gui.cpp, CMake XLION_LINUX_GUI); never seen by MSVC.
//
//  - the C entry points below are what the <windows.h> stand-in (linux_win32_shim/windows.h) calls for its user32/shell32
//    functions (monitors, cursor position, message box, file dialogs, ShellExecute). They are WEAK there: xLION_Headless and
//    the engine libraries never link this file, so the shim's failing stubs keep answering for them.
//  - xlion::linux_gui is what the editor's frame calls: the X11 clipboard for ImGui and the mouse cursor shapes.
//
// The window system is reached through Xlib on a connection of its own (the window ids are global to the X server, so
// the cursor can be set on xGPU's windows). Dialogs and "open with the default app" run the desktop's own tools
// (zenity / kdialog, xdg-open; on WSL wslview or explorer.exe) - what is missing is reported once on stdout.
//
#if defined(_WIN32)
#error "xlion_linux_gui.h is Linux only"
#endif

extern "C"
{
    struct xlion_gui_monitor
    {
        int m_X, m_Y, m_W, m_H;                      // the monitor, in X screen coordinates
        int m_WorkX, m_WorkY, m_WorkW, m_WorkH;      // the part not taken by panels (the monitor when unknown)
        int m_bPrimary;
    };

    // Count written (at most Max), the primary monitor first. 0 when there is no X display.
    __attribute__((weak)) int  xlion_gui_EnumMonitors ( xlion_gui_monitor* pOut, int Max );
    // 1 and the pointer position in X screen coordinates, 0 without a display.
    __attribute__((weak)) int  xlion_gui_GetCursorPos ( int* pX, int* pY );
    // Win32 MessageBox flags (MB_OK, MB_YESNO, MB_OKCANCEL, MB_ICON*) and result (IDOK, IDCANCEL, IDYES, IDNO). UTF-8 text.
    __attribute__((weak)) int  xlion_gui_MessageBox   ( const char* pText, const char* pCaption, unsigned Type );
    // Mode 0 = open a file, 1 = save a file, 2 = pick a folder. pFilter is a Win32 filter ("Name\0*.a;*.b\0...\0\0") or null.
    // 1 and the UTF-8 path in pOut when one was picked, 0 when cancelled or no dialog tool is installed.
    __attribute__((weak)) int  xlion_gui_FileDialog   ( int Mode, const char* pTitle, const char* pInitial, const char* pFilter, char* pOut, int OutSize );
    // Opens a file or folder with the desktop's default application (ShellExecute "open"/"explore"). 1 = launched.
    __attribute__((weak)) int  xlion_gui_ShellOpen    ( const char* pFile, const char* pParams, const char* pDir );
}

namespace xlion::linux_gui
{
    // After the ImGui context exists: ImGui's clipboard becomes the X11 CLIPBOARD selection (shared with every app, and with
    // Windows through WSLg); the main window gets its title (xGPU names every X window "LION").
    void Install    ( unsigned long MainWindow, const char* pTitle ) noexcept;
    // Every frame, after ImGui::NewFrame..Render decided the cursor: ImGui's mouse cursor shape on these X windows.
    void SetCursor  ( int ImGuiMouseCursor, const unsigned long* pWindows, int Count ) noexcept;
    // Before the ImGui context goes away.
    void Shutdown   ( void ) noexcept;
}
