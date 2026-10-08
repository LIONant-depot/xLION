//
// Linux port: desktop services of the graphical editor on X11 - see xlion_linux_gui.h.
// Its own translation unit (Xlib's macros - None, Bool, Status, ... - never reach the editor's code).
//
#include "imgui.h"                      // before Xlib: its macros would rename ImGui identifiers
#include "xlion_linux_gui.h"

#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <X11/cursorfont.h>

#include <dlfcn.h>
#include <poll.h>
#include <spawn.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

extern char** environ;

namespace
{
    //------------------------------------------------------------------------------------------------
    // Processes: the desktop tools (zenity, kdialog, xdg-open, ...)
    //------------------------------------------------------------------------------------------------

    bool HasProgram( const char* pName ) noexcept
    {
        const char* pPath = std::getenv("PATH");
        if( !pPath ) return false;
        std::string Paths(pPath);
        std::size_t Start = 0;
        while( Start <= Paths.size() )
        {
            const auto End = Paths.find(':', Start);
            const auto Dir = Paths.substr(Start, End == std::string::npos ? std::string::npos : End - Start);
            if( !Dir.empty() && ::access((Dir + "/" + pName).c_str(), X_OK) == 0 ) return true;
            if( End == std::string::npos ) break;
            Start = End + 1;
        }
        return false;
    }

    // Runs Args (PATH lookup), waits, collects stdout. -1 when it could not be started, else its exit code.
    int RunCapture( const std::vector<std::string>& Args, std::string& Out ) noexcept
    {
        Out.clear();
        int Pipe[2];
        if( ::pipe2(Pipe, O_CLOEXEC) != 0 ) return -1;

        posix_spawn_file_actions_t Actions;
        posix_spawn_file_actions_init(&Actions);
        posix_spawn_file_actions_adddup2(&Actions, Pipe[1], 1);
        posix_spawn_file_actions_addopen(&Actions, 0, "/dev/null", O_RDONLY, 0);

        std::vector<char*> Argv;
        for( auto& A : Args ) Argv.push_back(const_cast<char*>(A.c_str()));
        Argv.push_back(nullptr);

        pid_t Pid = 0;
        const int Err = ::posix_spawnp(&Pid, Argv[0], &Actions, nullptr, Argv.data(), environ);
        posix_spawn_file_actions_destroy(&Actions);
        ::close(Pipe[1]);
        if( Err != 0 ) { ::close(Pipe[0]); return -1; }

        char Buffer[4096];
        for(;;)
        {
            const auto n = ::read(Pipe[0], Buffer, sizeof(Buffer));
            if( n > 0 ) { Out.append(Buffer, static_cast<std::size_t>(n)); continue; }
            if( n < 0 && errno == EINTR ) continue;
            break;
        }
        ::close(Pipe[0]);

        int ExitStatus = 0;
        while( ::waitpid(Pid, &ExitStatus, 0) < 0 && errno == EINTR ) {}
        while( !Out.empty() && (Out.back() == '\n' || Out.back() == '\r') ) Out.pop_back();
        return WIFEXITED(ExitStatus) ? WEXITSTATUS(ExitStatus) : -1;
    }

    // Starts Args detached (its own session, no zombie left behind: double fork through a short-lived child).
    bool RunDetached( const std::vector<std::string>& Args, const std::string& Dir = {} ) noexcept
    {
        const pid_t Pid = ::fork();
        if( Pid < 0 ) return false;
        if( Pid == 0 )
        {
            ::setsid();
            if( ::fork() != 0 ) ::_exit(0);
            if( !Dir.empty() && ::chdir(Dir.c_str()) != 0 ) {}
            const int Null = ::open("/dev/null", O_RDWR);
            if( Null >= 0 ) { ::dup2(Null, 0); ::dup2(Null, 1); ::dup2(Null, 2); }
            std::vector<char*> Argv;
            for( auto& A : Args ) Argv.push_back(const_cast<char*>(A.c_str()));
            Argv.push_back(nullptr);
            ::execvp(Argv[0], Argv.data());
            ::_exit(127);
        }
        int ExitStatus = 0;
        while( ::waitpid(Pid, &ExitStatus, 0) < 0 && errno == EINTR ) {}
        return true;
    }

    bool IsWSL( void ) noexcept { return std::getenv("WSL_DISTRO_NAME") != nullptr || std::getenv("WSL_INTEROP") != nullptr; }

    // Paths reach this file in the editor's Windows spelling at times ("<project>\\Assets\\a.png"): outside tools need '/'.
    std::string PosixPath( const char* p ) noexcept
    {
        std::string S = p ? p : "";
        for( auto& c : S ) if( c == '\\' ) c = '/';
        return S;
    }

    void ReportMissingOnce( const char* pWhat ) noexcept
    {
        static std::mutex             s_Lock;
        static std::vector<std::string> s_Reported;
        std::lock_guard Lk(s_Lock);
        for( auto& R : s_Reported ) if( R == pWhat ) return;
        s_Reported.emplace_back(pWhat);
        std::printf("xLION (Linux): %s\n", pWhat);
        std::fflush(stdout);
    }

    //------------------------------------------------------------------------------------------------
    // The X connection of this file (opened on first use; null without a display)
    //------------------------------------------------------------------------------------------------

    struct x_state
    {
        Display*        m_pDisplay  { nullptr };
        bool            m_bTried    { false };
        std::mutex      m_Lock;
    };
    x_state g_X;

    Display* GetDisplay( void ) noexcept
    {
        std::lock_guard Lk(g_X.m_Lock);
        if( !g_X.m_bTried )
        {
            g_X.m_bTried   = true;
            XInitThreads();
            g_X.m_pDisplay = XOpenDisplay(nullptr);
        }
        return g_X.m_pDisplay;
    }

    //------------------------------------------------------------------------------------------------
    // Monitors (XRandR 1.5 monitors through dlopen - no build dependency on libXrandr's headers)
    //------------------------------------------------------------------------------------------------

    struct xrr_monitor_info { Atom name; int primary; int automatic; int noutput; int x, y, width, height, mwidth, mheight; unsigned long* outputs; };
    using xrr_get_monitors_fn  = xrr_monitor_info* (*)( Display*, Window, int, int* );
    using xrr_free_monitors_fn = void (*)( xrr_monitor_info* );

    struct monitor_cache
    {
        std::mutex                              m_Lock;
        std::vector<xlion_gui_monitor>          m_List;
        std::chrono::steady_clock::time_point   m_When {};
    };
    monitor_cache g_Monitors;

    std::vector<xlion_gui_monitor> QueryMonitors( Display* pDisplay ) noexcept
    {
        std::vector<xlion_gui_monitor> List;
        const int    Screen = DefaultScreen(pDisplay);
        const Window Root   = RootWindow(pDisplay, Screen);

        static void* s_pXrandr = ::dlopen("libXrandr.so.2", RTLD_NOW | RTLD_LOCAL);
        static auto  s_pGet    = s_pXrandr ? reinterpret_cast<xrr_get_monitors_fn >(::dlsym(s_pXrandr, "XRRGetMonitors"))  : nullptr;
        static auto  s_pFree   = s_pXrandr ? reinterpret_cast<xrr_free_monitors_fn>(::dlsym(s_pXrandr, "XRRFreeMonitors")) : nullptr;
        if( s_pGet && s_pFree )
        {
            int Count = 0;
            if( xrr_monitor_info* p = s_pGet(pDisplay, Root, 1, &Count) )
            {
                for( int i = 0; i < Count; ++i )
                {
                    const auto& M = p[i];
                    if( M.width <= 0 || M.height <= 0 ) continue;
                    xlion_gui_monitor G{ M.x, M.y, M.width, M.height, M.x, M.y, M.width, M.height, M.primary ? 1 : 0 };
                    if( G.m_bPrimary ) List.insert(List.begin(), G); else List.push_back(G);
                }
                s_pFree(p);
            }
        }
        if( List.empty() )
        {
            const int W = DisplayWidth(pDisplay, Screen), H = DisplayHeight(pDisplay, Screen);
            List.push_back({ 0, 0, W, H, 0, 0, W, H, 1 });
        }

        // _NET_WORKAREA (desktop 0) trims the work area of the monitors it overlaps, when the window manager publishes it
        Atom          Type = 0;
        int           Format = 0;
        unsigned long Items = 0, After = 0;
        unsigned char* pData = nullptr;
        // only_if_exists: WSLg may lack _NET_WORKAREA - None + XGetWindowProperty is BadAtom
        const Atom WorkArea = XInternAtom(pDisplay, "_NET_WORKAREA", True);
        if( WorkArea != None
         && XGetWindowProperty(pDisplay, Root, WorkArea, 0, 4, 0, XA_CARDINAL, &Type, &Format, &Items, &After, &pData) == 0
         && pData && Format == 32 && Items >= 4 )
        {
            const long* pL = reinterpret_cast<const long*>(pData);
            const int WX = static_cast<int>(pL[0]), WY = static_cast<int>(pL[1]), WW = static_cast<int>(pL[2]), WH = static_cast<int>(pL[3]);
            for( auto& M : List )
            {
                const int L = std::max(M.m_X, WX), T = std::max(M.m_Y, WY);
                const int R = std::min(M.m_X + M.m_W, WX + WW), B = std::min(M.m_Y + M.m_H, WY + WH);
                if( R - L > 0 && B - T > 0 ) { M.m_WorkX = L; M.m_WorkY = T; M.m_WorkW = R - L; M.m_WorkH = B - T; }
            }
        }
        if( pData ) XFree(pData);
        return List;
    }

    //------------------------------------------------------------------------------------------------
    // Clipboard: the CLIPBOARD selection, owned by a hidden window of this file's connection. A thread answers the
    // other applications' requests while we own it (SelectionRequest) and receives what we ask for (SelectionNotify).
    //------------------------------------------------------------------------------------------------

    struct clipboard
    {
        Display*                    m_pDisplay      { nullptr };
        Window                      m_Window        { 0 };
        Atom                        m_Clipboard     { 0 };
        Atom                        m_Utf8          { 0 };
        Atom                        m_Targets       { 0 };
        Atom                        m_Text          { 0 };
        Atom                        m_Property      { 0 };
        Atom                        m_Incr          { 0 };

        std::mutex                  m_Lock;
        std::condition_variable     m_Arrived;
        std::string                 m_Owned;                // what we put on the clipboard
        bool                        m_bOwner        { false };
        bool                        m_bReplied      { false };
        bool                        m_bReplyOk      { false };
        std::string                 m_Reply;                // what another application gave us
        std::string                 m_ForImGui;             // GetClipboardText's string must outlive the call

        std::atomic<bool>           m_bQuit         { false };
        std::thread                 m_Thread;
    };
    clipboard* g_pClipboard = nullptr;

    void AnswerRequest( clipboard& C, const XSelectionRequestEvent& R ) noexcept
    {
        XSelectionEvent Reply{};
        Reply.type      = SelectionNotify;
        Reply.display   = R.display;
        Reply.requestor = R.requestor;
        Reply.selection = R.selection;
        Reply.target    = R.target;
        Reply.time      = R.time;
        Reply.property  = 0;                                            // refused unless we fill it below

        const Atom Property = R.property ? R.property : R.target;       // obsolete clients pass None: use the target
        std::string Text;
        {
            std::lock_guard Lk(C.m_Lock);
            Text = C.m_bOwner ? C.m_Owned : std::string{};
        }

        if( R.target == C.m_Targets )
        {
            const Atom List[] = { C.m_Targets, C.m_Utf8, XA_STRING, C.m_Text };
            XChangeProperty(C.m_pDisplay, R.requestor, Property, XA_ATOM, 32, PropModeReplace, reinterpret_cast<const unsigned char*>(List), 4);
            Reply.property = Property;
        }
        else if( R.target == C.m_Utf8 || R.target == XA_STRING || R.target == C.m_Text )
        {
            const Atom Type = (R.target == XA_STRING) ? XA_STRING : C.m_Utf8;
            XChangeProperty(C.m_pDisplay, R.requestor, Property, Type, 8, PropModeReplace, reinterpret_cast<const unsigned char*>(Text.data()), static_cast<int>(Text.size()));
            Reply.property = Property;
        }

        XEvent E{};
        E.xselection = Reply;
        XSendEvent(C.m_pDisplay, R.requestor, 0, 0, &E);
        XFlush(C.m_pDisplay);
    }

    void ReceiveReply( clipboard& C, const XSelectionEvent& S ) noexcept
    {
        std::string Data;
        bool        bOk = false;
        if( S.property )
        {
            Atom           Type = 0;
            int            Format = 0;
            unsigned long  Items = 0, After = 0;
            unsigned char* pData = nullptr;
            if( XGetWindowProperty(C.m_pDisplay, C.m_Window, S.property, 0, 0x1FFFFFFF, 1, AnyPropertyType, &Type, &Format, &Items, &After, &pData) == 0 )
            {
                if( Type != C.m_Incr && pData && Format == 8 ) { Data.assign(reinterpret_cast<const char*>(pData), Items); bOk = true; }
                else if( Type == C.m_Incr ) ReportMissingOnce("clipboard: the other application sends its text in pieces (INCR), which is not supported - not pasted");
            }
            if( pData ) XFree(pData);
        }
        std::lock_guard Lk(C.m_Lock);
        C.m_Reply    = std::move(Data);
        C.m_bReplyOk = bOk;
        C.m_bReplied = true;
        C.m_Arrived.notify_all();
    }

    void ClipboardThread( clipboard& C ) noexcept
    {
        const int Fd = ConnectionNumber(C.m_pDisplay);
        while( !C.m_bQuit.load() )
        {
            pollfd P{ Fd, POLLIN, 0 };
            ::poll(&P, 1, 50);
            while( XPending(C.m_pDisplay) )
            {
                XEvent E;
                XNextEvent(C.m_pDisplay, &E);
                switch( E.type )
                {
                case SelectionRequest: AnswerRequest(C, E.xselectionrequest); break;
                case SelectionNotify:  ReceiveReply(C, E.xselection);         break;
                case SelectionClear:
                    {
                        std::lock_guard Lk(C.m_Lock);
                        C.m_bOwner = false;
                    }
                    break;
                default: break;
                }
            }
        }
    }

    void SetClipboard( ImGuiContext*, const char* pText ) noexcept
    {
        auto* pC = g_pClipboard;
        if( !pC ) return;
        {
            std::lock_guard Lk(pC->m_Lock);
            pC->m_Owned  = pText ? pText : "";
            pC->m_bOwner = true;
        }
        XSetSelectionOwner(pC->m_pDisplay, pC->m_Clipboard, pC->m_Window, CurrentTime);
        const bool bOwner = XGetSelectionOwner(pC->m_pDisplay, pC->m_Clipboard) == pC->m_Window;
        if( !bOwner ) { std::lock_guard Lk(pC->m_Lock); pC->m_bOwner = false; }
        XFlush(pC->m_pDisplay);
    }

    const char* GetClipboard( ImGuiContext* ) noexcept
    {
        auto* pC = g_pClipboard;
        if( !pC ) return "";
        {
            std::lock_guard Lk(pC->m_Lock);
            if( pC->m_bOwner ) { pC->m_ForImGui = pC->m_Owned; return pC->m_ForImGui.c_str(); }
        }

        // Ask the owner: UTF-8 first, then plain STRING for old applications
        for( const Atom Target : { pC->m_Utf8, static_cast<Atom>(XA_STRING) } )
        {
            {
                std::lock_guard Lk(pC->m_Lock);
                pC->m_bReplied = false;
            }
            XConvertSelection(pC->m_pDisplay, pC->m_Clipboard, Target, pC->m_Property, pC->m_Window, CurrentTime);
            XFlush(pC->m_pDisplay);

            std::unique_lock Lk(pC->m_Lock);
            if( pC->m_Arrived.wait_for(Lk, std::chrono::milliseconds(500), [&]{ return pC->m_bReplied; }) && pC->m_bReplyOk )
            {
                pC->m_ForImGui = pC->m_Reply;
                return pC->m_ForImGui.c_str();
            }
        }
        std::lock_guard Lk(pC->m_Lock);
        pC->m_ForImGui.clear();
        return pC->m_ForImGui.c_str();
    }

    //------------------------------------------------------------------------------------------------
    // Mouse cursors: the desktop's cursor theme (libXcursor through dlopen) or X's core cursor font
    //------------------------------------------------------------------------------------------------

    struct cursors
    {
        Cursor  m_Shapes[ImGuiMouseCursor_COUNT] {};
        Cursor  m_Blank     { 0 };
        int     m_Current   { -2 };
        std::vector<unsigned long> m_Windows;
    };
    cursors g_Cursors;

    Cursor LoadShape( Display* pDisplay, int ImGuiCursor ) noexcept
    {
        using load_fn = Cursor (*)( Display*, const char* );
        static void* s_pXcursor = ::dlopen("libXcursor.so.1", RTLD_NOW | RTLD_LOCAL);
        static auto  s_pLoad    = s_pXcursor ? reinterpret_cast<load_fn>(::dlsym(s_pXcursor, "XcursorLibraryLoadCursor")) : nullptr;

        struct shape { const char* m_pName; const char* m_pAlt; unsigned m_Font; };
        static const shape Shapes[ImGuiMouseCursor_COUNT] =
        { { "default",     "left_ptr",            XC_left_ptr            }   // Arrow
        , { "text",        "xterm",               XC_xterm               }   // TextInput
        , { "all-scroll",  "fleur",               XC_fleur               }   // ResizeAll
        , { "ns-resize",   "sb_v_double_arrow",   XC_sb_v_double_arrow   }   // ResizeNS
        , { "ew-resize",   "sb_h_double_arrow",   XC_sb_h_double_arrow   }   // ResizeEW
        , { "nesw-resize", "bottom_left_corner",  XC_bottom_left_corner  }   // ResizeNESW
        , { "nwse-resize", "bottom_right_corner", XC_bottom_right_corner }   // ResizeNWSE
        , { "pointer",     "hand2",               XC_hand2               }   // Hand
        , { "wait",        "watch",               XC_watch               }   // Wait
        , { "progress",    "left_ptr_watch",      XC_watch               }   // Progress
        , { "not-allowed", "crossed_circle",      XC_X_cursor            }   // NotAllowed
        };
        if( ImGuiCursor < 0 || ImGuiCursor >= ImGuiMouseCursor_COUNT ) ImGuiCursor = ImGuiMouseCursor_Arrow;
        const auto& S = Shapes[ImGuiCursor];
        if( s_pLoad )
        {
            if( Cursor c = s_pLoad(pDisplay, S.m_pName) ) return c;
            if( Cursor c = s_pLoad(pDisplay, S.m_pAlt ) ) return c;
        }
        return XCreateFontCursor(pDisplay, S.m_Font);
    }
}

//====================================================================================================
// The shim's entry points
//====================================================================================================

extern "C" int xlion_gui_EnumMonitors( xlion_gui_monitor* pOut, int Max )
{
    Display* pDisplay = GetDisplay();
    if( !pDisplay || !pOut || Max <= 0 ) return 0;

    // ImGui asks every frame: the layout is read again at most twice a second
    std::lock_guard Lk(g_Monitors.m_Lock);
    const auto Now = std::chrono::steady_clock::now();
    if( g_Monitors.m_List.empty() || Now - g_Monitors.m_When > std::chrono::milliseconds(500) )
    {
        std::lock_guard XLk(g_X.m_Lock);
        g_Monitors.m_List = QueryMonitors(pDisplay);
        g_Monitors.m_When = Now;
    }
    const int n = std::min<int>(Max, static_cast<int>(g_Monitors.m_List.size()));
    for( int i = 0; i < n; ++i ) pOut[i] = g_Monitors.m_List[static_cast<std::size_t>(i)];
    return n;
}

extern "C" int xlion_gui_GetCursorPos( int* pX, int* pY )
{
    Display* pDisplay = GetDisplay();
    if( !pDisplay ) return 0;
    std::lock_guard Lk(g_X.m_Lock);
    Window       RootRet = 0, ChildRet = 0;
    int          RX = 0, RY = 0, WX = 0, WY = 0;
    unsigned int Mask = 0;
    if( !XQueryPointer(pDisplay, DefaultRootWindow(pDisplay), &RootRet, &ChildRet, &RX, &RY, &WX, &WY, &Mask) ) return 0;
    if( pX ) *pX = RX;
    if( pY ) *pY = RY;
    return 1;
}

extern "C" int xlion_gui_MessageBox( const char* pText, const char* pCaption, unsigned Type )
{
    constexpr unsigned MB_TYPEMASK_ = 0xF, MB_ICONMASK_ = 0xF0;
    constexpr unsigned MB_OKCANCEL_ = 1, MB_YESNOCANCEL_ = 3, MB_YESNO_ = 4;
    constexpr unsigned MB_ICONERROR_ = 0x10, MB_ICONQUESTION_ = 0x20, MB_ICONWARNING_ = 0x30;
    constexpr int IDOK_ = 1, IDCANCEL_ = 2, IDYES_ = 6, IDNO_ = 7;

    const std::string Text    = pText    ? pText    : "";
    const std::string Caption = pCaption ? pCaption : "xLION";
    const unsigned    Buttons = Type & MB_TYPEMASK_;
    const unsigned    Icon    = Type & MB_ICONMASK_;
    const bool        bAsk    = Buttons == MB_YESNO_ || Buttons == MB_YESNOCANCEL_ || Buttons == MB_OKCANCEL_;

    std::fprintf(stderr, "[%s] %s\n", Caption.c_str(), Text.c_str());

    std::string Out;
    if( std::getenv("DISPLAY") && HasProgram("zenity") )
    {
        std::vector<std::string> Args{ "zenity", bAsk ? "--question" : (Icon == MB_ICONERROR_ ? "--error" : Icon == MB_ICONWARNING_ ? "--warning" : "--info")
                                     , "--title=" + Caption, "--text=" + Text, "--no-markup" };
        if( Buttons == MB_OKCANCEL_ ) { Args.push_back("--ok-label=OK"); Args.push_back("--cancel-label=Cancel"); }
        const int Rc = RunCapture(Args, Out);
        if( Rc >= 0 ) return bAsk ? (Rc == 0 ? (Buttons == MB_OKCANCEL_ ? IDOK_ : IDYES_) : (Buttons == MB_YESNO_ ? IDNO_ : IDCANCEL_)) : IDOK_;
    }
    if( std::getenv("DISPLAY") && HasProgram("kdialog") )
    {
        std::vector<std::string> Args{ "kdialog", "--title", Caption, bAsk ? "--yesno" : (Icon == MB_ICONERROR_ ? "--error" : "--msgbox"), Text };
        const int Rc = RunCapture(Args, Out);
        if( Rc >= 0 ) return bAsk ? (Rc == 0 ? (Buttons == MB_OKCANCEL_ ? IDOK_ : IDYES_) : (Buttons == MB_YESNO_ ? IDNO_ : IDCANCEL_)) : IDOK_;
    }
    (void)MB_ICONQUESTION_;
    ReportMissingOnce("message boxes print to stderr only - install zenity (or kdialog) for real ones");
    return bAsk ? (Buttons == MB_OKCANCEL_ ? IDCANCEL_ : (Buttons == MB_YESNO_ ? IDNO_ : IDCANCEL_)) : IDOK_;
}

extern "C" int xlion_gui_FileDialog( int Mode, const char* pTitle, const char* pInitial, const char* pFilter, char* pOut, int OutSize )
{
    if( !pOut || OutSize <= 1 ) return 0;
    pOut[0] = 0;
    if( !std::getenv("DISPLAY") ) return 0;

    // "Name\0*.a;*.b\0Name2\0*.*\0\0" -> pairs
    std::vector<std::pair<std::string, std::string>> Filters;
    if( pFilter )
    {
        const char* p = pFilter;
        while( *p )
        {
            std::string Name = p; p += Name.size() + 1;
            if( !*p ) break;
            std::string Spec = p; p += Spec.size() + 1;
            for( auto& c : Spec ) if( c == ';' ) c = ' ';
            Filters.emplace_back(std::move(Name), std::move(Spec));
        }
    }
    const std::string Title   = pTitle ? pTitle : (Mode == 2 ? "Select a folder" : Mode == 1 ? "Save as" : "Open");
    std::string       Initial = PosixPath(pInitial);
    if( !Initial.empty() && Mode == 2 && Initial.back() != '/' ) Initial += '/';

    std::string Out;
    int         Rc = -1;
    if( HasProgram("zenity") )
    {
        std::vector<std::string> Args{ "zenity", "--file-selection", "--title=" + Title };
        if( Mode == 1 ) { Args.push_back("--save"); Args.push_back("--confirm-overwrite"); }
        if( Mode == 2 ) Args.push_back("--directory");
        if( !Initial.empty() ) Args.push_back("--filename=" + Initial);
        for( auto& [Name, Spec] : Filters ) Args.push_back("--file-filter=" + Name + " | " + Spec);
        Rc = RunCapture(Args, Out);
    }
    else if( HasProgram("kdialog") )
    {
        std::string Spec;
        for( auto& [Name, S] : Filters ) { if( !Spec.empty() ) Spec += "\n"; Spec += Name + " (" + S + ")"; }
        std::vector<std::string> Args{ "kdialog", "--title", Title, Mode == 2 ? "--getexistingdirectory" : Mode == 1 ? "--getsavefilename" : "--getopenfilename"
                                     , Initial.empty() ? std::string(".") : Initial };
        if( Mode != 2 && !Spec.empty() ) Args.push_back(Spec);
        Rc = RunCapture(Args, Out);
    }
    else
    {
        ReportMissingOnce("file dialogs need zenity (or kdialog) - none is installed, the dialog was not shown");
        return 0;
    }
    if( Rc != 0 || Out.empty() ) return 0;
    if( static_cast<int>(Out.size()) >= OutSize ) return 0;
    std::memcpy(pOut, Out.c_str(), Out.size() + 1);
    return 1;
}

extern "C" int xlion_gui_ShellOpen( const char* pFile, const char* pParams, const char* pDir )
{
    const std::string File = PosixPath(pFile);
    if( File.empty() ) return 0;
    const std::string Dir = PosixPath(pDir);

    // An executable with parameters is run as is (ShellExecute "open" on a program)
    if( pParams && *pParams && ::access(File.c_str(), X_OK) == 0 && !std::filesystem::is_directory(File) )
        return RunDetached({ "/bin/sh", "-c", "exec \"$0\" " + std::string(pParams), File }, Dir) ? 1 : 0;

    if( IsWSL() )
    {
        // WSL: the Windows side opens it (its file associations, Explorer for folders)
        if( HasProgram("wslview") ) return RunDetached({ "wslview", File }, Dir) ? 1 : 0;
        std::string WinPath;
        if( RunCapture({ "wslpath", "-w", std::filesystem::absolute(File).string() }, WinPath) == 0 && !WinPath.empty() )
        {
            if( std::filesystem::is_directory(File) ) return RunDetached({ "explorer.exe", WinPath }) ? 1 : 0;
            return RunDetached({ "cmd.exe", "/c", "start", "", WinPath }, "/mnt/c") ? 1 : 0;
        }
    }
    if( HasProgram("xdg-open") ) return RunDetached({ "xdg-open", File }, Dir) ? 1 : 0;
    if( HasProgram("gio") )      return RunDetached({ "gio", "open", File }, Dir) ? 1 : 0;
    ReportMissingOnce("opening files with their application needs xdg-open (xdg-utils) - none is installed");
    return 0;
}

//====================================================================================================
// What the editor's frame calls
//====================================================================================================

namespace xlion::linux_gui
{
    void Install( unsigned long MainWindow, const char* pTitle ) noexcept
    {
        if( Display* pTitleDisplay = GetDisplay(); pTitleDisplay && MainWindow && pTitle )
        {
            std::lock_guard Lk(g_X.m_Lock);
            XStoreName(pTitleDisplay, MainWindow, pTitle);
            XChangeProperty(pTitleDisplay, MainWindow, XInternAtom(pTitleDisplay, "_NET_WM_NAME", 0), XInternAtom(pTitleDisplay, "UTF8_STRING", 0), 8, PropModeReplace
                           , reinterpret_cast<const unsigned char*>(pTitle), static_cast<int>(std::strlen(pTitle)));
            XFlush(pTitleDisplay);
        }

        if( g_pClipboard ) return;
        XInitThreads();
        Display* pDisplay = XOpenDisplay(nullptr);          // the clipboard's own connection: its thread reads all of its events
        if( !pDisplay ) return;

        auto* pC = new clipboard;
        pC->m_pDisplay  = pDisplay;
        pC->m_Window    = XCreateSimpleWindow(pDisplay, DefaultRootWindow(pDisplay), -10, -10, 1, 1, 0, 0, 0);
        pC->m_Clipboard = XInternAtom(pDisplay, "CLIPBOARD",       0);
        pC->m_Utf8      = XInternAtom(pDisplay, "UTF8_STRING",     0);
        pC->m_Targets   = XInternAtom(pDisplay, "TARGETS",         0);
        pC->m_Text      = XInternAtom(pDisplay, "TEXT",            0);
        pC->m_Property  = XInternAtom(pDisplay, "XLION_CLIPBOARD", 0);
        pC->m_Incr      = XInternAtom(pDisplay, "INCR",            0);
        XFlush(pDisplay);
        pC->m_Thread    = std::thread(ClipboardThread, std::ref(*pC));
        g_pClipboard    = pC;

        ImGuiPlatformIO& PlatformIO = ImGui::GetPlatformIO();
        PlatformIO.Platform_SetClipboardTextFn = [](ImGuiContext* pCtx, const char* pText) { SetClipboard(pCtx, pText); };
        PlatformIO.Platform_GetClipboardTextFn = [](ImGuiContext* pCtx) -> const char* { return GetClipboard(pCtx); };
    }

    void SetCursor( int ImGuiCursor, const unsigned long* pWindows, int Count ) noexcept
    {
        Display* pDisplay = GetDisplay();
        if( !pDisplay || !pWindows || Count <= 0 ) return;

        // Only when the shape or the set of windows changed (a viewport window was created)
        bool bSameWindows = static_cast<int>(g_Cursors.m_Windows.size()) == Count;
        for( int i = 0; bSameWindows && i < Count; ++i ) bSameWindows = g_Cursors.m_Windows[static_cast<std::size_t>(i)] == pWindows[i];
        if( bSameWindows && ImGuiCursor == g_Cursors.m_Current ) return;

        std::lock_guard Lk(g_X.m_Lock);
        Cursor C = 0;
        if( ImGuiCursor == ImGuiMouseCursor_None )
        {
            if( !g_Cursors.m_Blank )
            {
                static const char Bits[1] = { 0 };
                Pixmap P = XCreateBitmapFromData(pDisplay, DefaultRootWindow(pDisplay), Bits, 1, 1);
                XColor Black{};
                g_Cursors.m_Blank = XCreatePixmapCursor(pDisplay, P, P, &Black, &Black, 0, 0);
                XFreePixmap(pDisplay, P);
            }
            C = g_Cursors.m_Blank;
        }
        else
        {
            const int Index = (ImGuiCursor >= 0 && ImGuiCursor < ImGuiMouseCursor_COUNT) ? ImGuiCursor : ImGuiMouseCursor_Arrow;
            if( !g_Cursors.m_Shapes[Index] ) g_Cursors.m_Shapes[Index] = LoadShape(pDisplay, Index);
            C = g_Cursors.m_Shapes[Index];
        }
        for( int i = 0; i < Count; ++i ) if( pWindows[i] ) XDefineCursor(pDisplay, pWindows[i], C);
        XFlush(pDisplay);

        g_Cursors.m_Current = ImGuiCursor;
        g_Cursors.m_Windows.assign(pWindows, pWindows + Count);
    }

    void Shutdown( void ) noexcept
    {
        if( auto* pC = g_pClipboard )
        {
            if( ImGui::GetCurrentContext() )
            {
                ImGuiPlatformIO& PlatformIO = ImGui::GetPlatformIO();
                PlatformIO.Platform_SetClipboardTextFn = nullptr;
                PlatformIO.Platform_GetClipboardTextFn = nullptr;
            }
            pC->m_bQuit = true;
            if( pC->m_Thread.joinable() ) pC->m_Thread.join();
            XDestroyWindow(pC->m_pDisplay, pC->m_Window);
            XCloseDisplay(pC->m_pDisplay);
            g_pClipboard = nullptr;
            delete pC;
        }
    }
}
