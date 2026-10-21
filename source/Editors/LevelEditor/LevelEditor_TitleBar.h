#pragma once

#include <cfloat>
#include <chrono>
#include <cstdio>
#include <filesystem>
#include <iterator>
#include <memory>
#include <string>
#include <vector>

#include "source/Assets/xlion_icon_resource.h"
#include "source/Tools/xgpu_xcore_bitmap_helpers.h"
#include "dependencies/xbmp_tools/src/xbmp_tools.h"
#include "imgui_internal.h"

//-----------------------------------------------------------------------------------
// The editor's own title bar (Windows): the OS caption is taken away and this bar is drawn in its place, the color
// of the dock tab strip right below it (the two read as one dark band). Left: "Project: <project>". Center: the
// xLION wordmark. Right of the wordmark: the frame rate and its history. Far right: minimize, maximize, close.
//
// Only the drawing is ImGui; the mouse on the bar is the OS's: the window's WM_NCHITTEST says HTCAPTION over the
// bar (drag, double-click to maximize, Aero Snap, right-click system menu all stay native), HTMIN/MAX/CLOSE over
// the three buttons (Windows 11 shows its snap layouts over Maximize), the resize edges as they were, and
// HTCLIENT where an ImGui window (a popup, a floating panel) lies over the bar. The bar itself takes no input.
//
// The window is xGPU's (xgpu_windows_window.cpp): its procedure is subclassed here, so xGPU itself is unchanged
// and its other windows (the detached viewports) keep their native frames.
//-----------------------------------------------------------------------------------
namespace level_editor::title_bar
{
    struct rect
    {
        float m_X0 = 0, m_Y0 = 0, m_X1 = 0, m_Y1 = 0;
        bool Contains(float X, float Y) const noexcept { return X >= m_X0 && X < m_X1 && Y >= m_Y0 && Y < m_Y1; }
    };

    enum button : int { BUTTON_NONE = -1, BUTTON_MINIMIZE, BUTTON_MAXIMIZE, BUTTON_CLOSE, BUTTON_COUNT };

    // The frame rate, sampled at a fixed pace (so the graph always spans the same time, whatever the rate is)
    struct fps_history
    {
        static constexpr int    count_v    = 96;            // one sample a pixel of the graph
        static constexpr double interval_v = 0.125;         // seconds a sample: the graph shows the last 12 seconds

        using clock = std::chrono::steady_clock;

        float             m_Samples[count_v] = {};
        int               m_Next   = 0;                     // where the next sample goes (the oldest one)
        int               m_Filled = 0;
        int               m_Frames = 0;
        clock::time_point m_Start  = clock::now();

        void Frame() noexcept
        {
            ++m_Frames;
            const auto   Now     = clock::now();
            const double Elapsed = std::chrono::duration<double>(Now - m_Start).count();
            if (Elapsed < interval_v) return;
            // A long stall (a modal OS loop: the window being dragged) is one slow sample, not many
            m_Samples[m_Next] = static_cast<float>(m_Frames / Elapsed);
            m_Next   = (m_Next + 1) % count_v;
            m_Filled = m_Filled < count_v ? m_Filled + 1 : count_v;
            m_Frames = 0;
            m_Start  = Now;
        }

        float Sample(int Age) const noexcept { return m_Samples[(m_Next - 1 - Age + count_v * 2) % count_v]; }   // Age 0 = the latest

        // What the counter shows: the last half second, so it can be read
        float Current() const noexcept
        {
            const int N = m_Filled < 4 ? m_Filled : 4;
            if (N == 0) return 0;
            float Sum = 0;
            for (int i = 0; i < N; ++i) Sum += Sample(i);
            return Sum / N;
        }
    };

    struct state
    {
        float             m_Height = 0;                     // of the bar, in client pixels (0: not drawn yet - the OS caption hit-test is not taken over)
        rect              m_Buttons[BUTTON_COUNT];          // client coordinates, as the hit-test wants them
        std::vector<rect> m_Holes;                          // the ImGui windows over the bar: they get the mouse
        int               m_Hot     = BUTTON_NONE;          // the button the mouse is over (set by the window procedure)
        int               m_Pressed = BUTTON_NONE;
        fps_history       m_Fps;
        std::wstring      m_ProjectPath;                    // what m_ProjectName was made from
        std::string       m_ProjectName;
#if defined(_WIN32)
        HWND              m_hWnd     = nullptr;
        WNDPROC           m_PrevProc = nullptr;
        HICON             m_hIcon    = nullptr;
#endif
    };

    inline state& State() noexcept { static state S; return S; }

    // The project's name as a person calls it: its folder's, without the .lionprj
    inline std::string ProjectName(const std::wstring& ProjectPath) noexcept
    {
        if (ProjectPath.empty()) return "No project";
        std::filesystem::path Path(ProjectPath);
        while (!Path.empty() && !Path.has_filename()) Path = Path.parent_path();      // a trailing separator
        if (Path.extension() == L".lionprj") Path = Path.stem();
        else                                 Path = Path.filename();
        const std::u8string U8 = Path.u8string();
        return std::string(U8.begin(), U8.end());
    }

#if defined(_WIN32)
    inline std::filesystem::path BrandAssetPath(const wchar_t* pName) noexcept
    {
        wchar_t ModulePath[MAX_PATH] = {};
        const DWORD Length = GetModuleFileNameW(nullptr, ModulePath, static_cast<DWORD>(std::size(ModulePath)));
        const std::filesystem::path ModuleDir = Length == 0 || Length >= std::size(ModulePath)
            ? std::filesystem::path()
            : std::filesystem::path(ModulePath).parent_path();
        std::error_code Ec;
        if (!ModuleDir.empty() && std::filesystem::exists(ModuleDir / pName, Ec)) return ModuleDir / pName;

        // Development builds place the executable below Build\ while the source asset stays in source\Assets\.
        for (std::filesystem::path Dir = ModuleDir; !Dir.empty(); Dir = Dir.parent_path())
        {
            const auto Candidate = Dir / L"source" / L"Assets" / pName;
            if (std::filesystem::exists(Candidate, Ec)) return Candidate;
            if (Dir == Dir.parent_path()) break;
        }

        const auto WorkingDirectoryCandidate = std::filesystem::current_path(Ec) / L"source" / L"Assets" / pName;
        if (!Ec && std::filesystem::exists(WorkingDirectoryCandidate, Ec)) return WorkingDirectoryCandidate;
        return ModuleDir.empty() ? std::filesystem::path(pName) : ModuleDir / pName;
    }

    inline std::filesystem::path BrandTexturePath() noexcept { return BrandAssetPath(L"xlion_icon.png"); }

    inline int ButtonHitCode(int Button) noexcept
    {
        switch (Button)
        {
        case BUTTON_MINIMIZE: return HTMINBUTTON;
        case BUTTON_MAXIMIZE: return HTMAXBUTTON;
        case BUTTON_CLOSE:    return HTCLOSE;
        default:              return HTNOWHERE;
        }
    }

    inline int ButtonOfHitCode(WPARAM Hit) noexcept
    {
        switch (Hit)
        {
        case HTMINBUTTON: return BUTTON_MINIMIZE;
        case HTMAXBUTTON: return BUTTON_MAXIMIZE;
        case HTCLOSE:     return BUTTON_CLOSE;
        default:          return BUTTON_NONE;
        }
    }

    inline LRESULT CALLBACK WindowProc(HWND hWnd, UINT Msg, WPARAM wParam, LPARAM lParam) noexcept
    {
        auto& S = State();
        switch (Msg)
        {
        case WM_NCCALCSIZE:
            if (wParam == TRUE)
            {
                // The default frame, minus its top: the sides and the bottom keep their native resize borders (and Windows 10's
                // invisible ones), the caption and the top border become client area for the bar to be drawn in
                auto&      Params      = *reinterpret_cast<NCCALCSIZE_PARAMS*>(lParam);
                const LONG OriginalTop = Params.rgrc[0].top;
                const LRESULT Result   = CallWindowProc(S.m_PrevProc, hWnd, Msg, wParam, lParam);
                if (Result != 0) return Result;
                Params.rgrc[0].top = OriginalTop;
                // Maximized, the window hangs over the monitor's edges by its frame: the bar starts where the monitor does
                if (IsZoomed(hWnd)) Params.rgrc[0].top += GetSystemMetrics(SM_CYFRAME) + GetSystemMetrics(SM_CXPADDEDBORDER);
                return 0;
            }
            break;

        case WM_NCHITTEST:
        {
            // The sides and the bottom are still the default frame's
            if (const LRESULT Hit = CallWindowProc(S.m_PrevProc, hWnd, Msg, wParam, lParam); Hit != HTCLIENT) return Hit;
            if (S.m_Height <= 0) return HTCLIENT;

            POINT Pt{ static_cast<short>(LOWORD(lParam)), static_cast<short>(HIWORD(lParam)) };
            ScreenToClient(hWnd, &Pt);
            const float X = static_cast<float>(Pt.x);
            const float Y = static_cast<float>(Pt.y);

            // The top edge resizes, as it did when it was the native frame's
            if (!IsZoomed(hWnd) && Pt.y >= 0 && Pt.y < GetSystemMetrics(SM_CYFRAME))
            {
                RECT Client;
                GetClientRect(hWnd, &Client);
                const int Corner = GetSystemMetrics(SM_CXFRAME) + GetSystemMetrics(SM_CXPADDEDBORDER);
                if (Pt.x < Corner)                return HTTOPLEFT;
                if (Pt.x >= Client.right - Corner) return HTTOPRIGHT;
                return HTTOP;
            }
            if (Y >= S.m_Height) return HTCLIENT;
            for (const auto& Hole : S.m_Holes) if (Hole.Contains(X, Y)) return HTCLIENT;
            for (int i = 0; i < BUTTON_COUNT; ++i) if (S.m_Buttons[i].Contains(X, Y)) return ButtonHitCode(i);
            return HTCAPTION;
        }

        // The buttons are pressed here, not by DefWindowProc (it would draw the classic caption buttons over the bar)
        case WM_NCMOUSEMOVE:
        {
            S.m_Hot = ButtonOfHitCode(wParam);
            if (S.m_Pressed != BUTTON_NONE && S.m_Pressed != S.m_Hot) S.m_Pressed = BUTTON_NONE;
            TRACKMOUSEEVENT Track{ sizeof(TRACKMOUSEEVENT), TME_LEAVE | TME_NONCLIENT, hWnd, 0 };
            TrackMouseEvent(&Track);
            // The mouse left the client area for the bar: ImGui must not keep the last thing it was over hovered
            if (!xgpu::virtual_input::Active() && ImGui::GetCurrentContext()) ImGui::GetIO().AddMousePosEvent(-FLT_MAX, -FLT_MAX);
            break;
        }
        case WM_NCMOUSELEAVE:
            S.m_Hot = S.m_Pressed = BUTTON_NONE;
            break;
        case WM_MOUSEMOVE:
            S.m_Hot = S.m_Pressed = BUTTON_NONE;
            break;
        case WM_NCLBUTTONDOWN:
        case WM_NCLBUTTONDBLCLK:
            if (const int Button = ButtonOfHitCode(wParam); Button != BUTTON_NONE)
            {
                S.m_Pressed = Button;
                return 0;
            }
            break;
        case WM_NCLBUTTONUP:
            if (const int Button = ButtonOfHitCode(wParam); Button != BUTTON_NONE)
            {
                // Through WM_SYSCOMMAND, as the native buttons do: the window animates, and Close goes the way Alt+F4 goes
                if (Button == S.m_Pressed)
                {
                    const WPARAM Command = Button == BUTTON_MINIMIZE ? SC_MINIMIZE
                                         : Button == BUTTON_CLOSE    ? SC_CLOSE
                                         : IsZoomed(hWnd)            ? SC_RESTORE
                                                                     : SC_MAXIMIZE;
                    PostMessage(hWnd, WM_SYSCOMMAND, Command, 0);
                }
                S.m_Pressed = BUTTON_NONE;
                return 0;
            }
            break;
        }
        return CallWindowProc(S.m_PrevProc, hWnd, Msg, wParam, lParam);
    }

    // Takes the OS caption away from the main window (once ImGui is up: the procedure reads its IO)
    inline void Install(xgpu::window& Window) noexcept
    {
        auto& S = State();
        if (S.m_hWnd) return;
        S.m_hWnd     = reinterpret_cast<HWND>(Window.getSystemWindowHandle());
        S.m_PrevProc = reinterpret_cast<WNDPROC>(SetWindowLongPtr(S.m_hWnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(&WindowProc)));
        S.m_hIcon    = static_cast<HICON>(LoadImageW(GetModuleHandleW(nullptr), MAKEINTRESOURCEW(IDI_XLION_ICON), IMAGE_ICON, 0, 0, LR_DEFAULTSIZE));
        if (S.m_hIcon)
        {
            SendMessageW(S.m_hWnd, WM_SETICON, ICON_BIG, reinterpret_cast<LPARAM>(S.m_hIcon));
            SendMessageW(S.m_hWnd, WM_SETICON, ICON_SMALL, reinterpret_cast<LPARAM>(S.m_hIcon));
        }
        // The frame is asked for again: the client area grows by the caption, WM_SIZE tells xGPU (a new swap chain)
        SetWindowPos(S.m_hWnd, nullptr, 0, 0, 0, 0, SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE);
    }

    // Before the window goes: its procedure is xGPU's again
    inline void Uninstall() noexcept
    {
        auto& S = State();
        if (S.m_hWnd == nullptr) return;
        SetWindowLongPtr(S.m_hWnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(S.m_PrevProc));
        if (S.m_hIcon)
        {
            DestroyIcon(S.m_hIcon);
            S.m_hIcon = nullptr;
        }
        S.m_hWnd     = nullptr;
        S.m_PrevProc = nullptr;
        S.m_Height   = 0;
    }
#endif

    inline std::unique_ptr<xgpu::texture> LoadBrandTexture(xgpu::device& Device) noexcept
    {
        auto pTexture = std::make_unique<xgpu::texture>();
        xbitmap Bitmap;
#if defined(_WIN32)
        const auto Path = BrandTexturePath();
#else
        const std::filesystem::path Path = "xlion_icon.png";
#endif
        const std::wstring PathWide = Path.wstring();
        if (xbmp::tools::loader::LoadSTDImage(Bitmap, PathWide))
        {
            std::fprintf(stderr, "xLION: unable to load the brand texture\n");
            return {};
        }
        if (xgpu::tools::bitmap::Create(*pTexture, Device, Bitmap))
        {
            std::fprintf(stderr, "xLION: unable to create the brand texture\n");
            return {};
        }
        return pTexture;
    }

    namespace details
    {
        inline ImU32 Color(int R, int G, int B, int A = 255) noexcept { return IM_COL32(R, G, B, A); }

        // The rate's color: green at a smooth frame rate, amber when it can be felt, red when it is a slideshow
        inline ImU32 FpsColor(float Fps, int Alpha = 255) noexcept
        {
            return Fps >= 50 ? Color(0x4C, 0xC3, 0x8A, Alpha)
                 : Fps >= 30 ? Color(0xE5, 0xB5, 0x47, Alpha)
                             : Color(0xE5, 0x53, 0x4B, Alpha);
        }

        struct glyph_run
        {
            const char* m_pText;
            ImU32       m_Top;                              // the run's gradient, top to bottom
            ImU32       m_Bottom;
        };

        inline float RunWidth(ImFont* pFont, float Size, const glyph_run* pRuns, int Count, float Tracking) noexcept
        {
            float Width = 0;
            int   Glyphs = 0;
            for (int r = 0; r < Count; ++r)
                for (const char* p = pRuns[r].m_pText; *p; ++p, ++Glyphs)
                    Width += pFont->CalcTextSizeA(Size, FLT_MAX, 0, p, p + 1).x;
            return Width + Tracking * (Glyphs > 0 ? Glyphs - 1 : 0);
        }

        // The wordmark: letter-spaced, each run shaded top to bottom, over a soft shadow
        inline void DrawWordmark(ImDrawList& DL, ImFont* pFont, float Size, ImVec2 Pos, const glyph_run* pRuns, int Count, float Tracking) noexcept
        {
            for (int Pass = 0; Pass < 2; ++Pass)
            {
                float X = Pos.x;
                for (int r = 0; r < Count; ++r)
                {
                    const int VtxStart = DL.VtxBuffer.Size;
                    for (const char* p = pRuns[r].m_pText; *p; ++p)
                    {
                        if (Pass == 0) DL.AddText(pFont, Size, ImVec2(X + 1.0f, Pos.y + 1.0f), Color(0, 0, 0, 150), p, p + 1);
                        else           DL.AddText(pFont, Size, ImVec2(X, Pos.y), IM_COL32_WHITE, p, p + 1);
                        X += pFont->CalcTextSizeA(Size, FLT_MAX, 0, p, p + 1).x + Tracking;
                    }
                    if (Pass == 1)
                        ImGui::ShadeVertsLinearColorGradientKeepAlpha(&DL, VtxStart, DL.VtxBuffer.Size, ImVec2(0, Pos.y + Size * 0.15f), ImVec2(0, Pos.y + Size * 0.95f), pRuns[r].m_Top, pRuns[r].m_Bottom);
                }
            }
        }

        // The frame rate over the last seconds: a filled area under its line, scaled to at least 60
        inline void DrawFpsGraph(ImDrawList& DL, const fps_history& History, ImVec2 Min, ImVec2 Max) noexcept
        {
            const float W = Max.x - Min.x;
            const float H = Max.y - Min.y;
            DL.AddRectFilled(Min, Max, Color(0x14, 0x14, 0x14), 2.0f);

            float Top = 60;
            for (int i = 0; i < History.m_Filled; ++i) Top = ImMax(Top, History.Sample(i));
            Top *= 1.1f;

            // 60 frames a second, as a reference
            const float Y60 = Max.y - H * (60.0f / Top);
            DL.AddLine(ImVec2(Min.x + 1, Y60), ImVec2(Max.x - 1, Y60), Color(0xFF, 0xFF, 0xFF, 28));

            const int N = ImMin(History.m_Filled, static_cast<int>(W) - 2);
            if (N < 2) return;
            ImVec2 Line[fps_history::count_v];
            for (int i = 0; i < N; ++i)
            {
                const float Fps = History.Sample(N - 1 - i);                  // oldest on the left
                const float X   = Max.x - 1 - static_cast<float>(N - 1 - i);
                const float Y   = Max.y - 1 - (H - 2) * ImClamp(Fps / Top, 0.0f, 1.0f);
                DL.AddRectFilled(ImVec2(X - 1, Y), ImVec2(X, Max.y - 1), FpsColor(Fps, 60));
                Line[i] = ImVec2(X - 0.5f, Y);
            }
            DL.AddPolyline(Line, N, FpsColor(History.Current()), ImDrawFlags_None, 1.0f);
        }
    }

    // Once a frame, right after BeginRendering (the bar reserves its height at the top of the main viewport, from the next frame on)
    inline void Draw(xgpu::window& Window, const std::wstring& ProjectPath, const xgpu::texture* pBrandIcon = nullptr) noexcept
    {
        auto& S = State();
        S.m_Fps.Frame();

        // The taskbar and Alt+Tab say the same thing as the bar
        if (S.m_ProjectName.empty() || S.m_ProjectPath != ProjectPath)
        {
            S.m_ProjectPath = ProjectPath;
            S.m_ProjectName = ProjectName(ProjectPath);
            Window.setTitle("xLION: " + S.m_ProjectName);
        }

        ImGuiIO&      IO       = ImGui::GetIO();
        ImFont*       pText    = IO.FontDefault ? IO.FontDefault : ImGui::GetFont();
        ImFont*       pLarge   = xgpu::tools::imgui::getLargeEmphasisFont();
        if (pLarge == nullptr) pLarge = pText;
        const float   TextSize  = pText->LegacySize;
        const float   LargeSize = pLarge->LegacySize;
        const float   Height    = ImFloor(LargeSize + 8.0f);
        const bool    bFocused  = Window.isFocused();

        // The tab strip's own backdrop (LevelEditor_Theme.h: TitleBg/TitleBgActive == TabDimmed/Tab): the bar and the strip are one band
        const ImVec4& Bg = ImGui::GetStyle().Colors[bFocused ? ImGuiCol_TitleBgActive : ImGuiCol_TitleBg];

        ImGuiViewport* pViewport = ImGui::GetMainViewport();
        ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding,    ImVec2(0, 0));
        ImGui::PushStyleVar(ImGuiStyleVar_WindowBorderSize, 0.0f);
        ImGui::PushStyleColor(ImGuiCol_WindowBg, Bg);
        constexpr ImGuiWindowFlags Flags = ImGuiWindowFlags_NoInputs | ImGuiWindowFlags_NoScrollbar | ImGuiWindowFlags_NoSavedSettings
                                         | ImGuiWindowFlags_NoFocusOnAppearing | ImGuiWindowFlags_NoBringToFrontOnFocus | ImGuiWindowFlags_NoNav;
        const bool bOpen = ImGui::BeginViewportSideBar("##xLIONTitleBar", pViewport, ImGuiDir_Up, Height, Flags);
        ImGui::PopStyleColor();
        ImGui::PopStyleVar(2);
        if (!bOpen)
        {
            ImGui::End();
            return;
        }

        ImGuiWindow* pBar  = ImGui::GetCurrentWindow();
        ImDrawList&  DL    = *pBar->DrawList;
        const ImVec2 Min   = pBar->Pos;
        const float  Width = pBar->Size.x;
        const float  MidY  = Min.y + Height * 0.5f;

        const ImU32 TextBright = ImGui::GetColorU32(bFocused ? ImVec4(0.93f, 0.93f, 0.93f, 1.0f) : ImVec4(0.60f, 0.60f, 0.60f, 1.0f));
        const ImU32 TextDim    = ImGui::GetColorU32(bFocused ? ImVec4(0.62f, 0.62f, 0.62f, 1.0f) : ImVec4(0.45f, 0.45f, 0.45f, 1.0f));

        //
        // Caption buttons, far right: 46 pixels each, the bar's whole height (the Windows 11 sizes)
        //
        constexpr float ButtonWidth = 46.0f;
        const float     ButtonsX    = Min.x + Width - ButtonWidth * static_cast<float>(BUTTON_COUNT);
#if defined(_WIN32)
        const bool bMaximized = S.m_hWnd && IsZoomed(S.m_hWnd);
#else
        const bool bMaximized = false;
#endif
        {
            static constexpr const char* Glyphs[BUTTON_COUNT] = { "\xEE\xA4\xA1", "\xEE\xA4\xA2", "\xEE\xA2\xBB" };   // Segoe MDL2: ChromeMinimize E921, ChromeMaximize E922, ChromeClose E8BB
            static constexpr const char* RestoreGlyph         = "\xEE\xA4\xA3";                                          // ChromeRestore E923
            for (int i = 0; i < BUTTON_COUNT; ++i)
            {
                const ImVec2 BMin(ButtonsX + ButtonWidth * i, Min.y);
                const ImVec2 BMax(BMin.x + ButtonWidth, Min.y + Height);
                S.m_Buttons[i] = { BMin.x - pViewport->Pos.x, BMin.y - pViewport->Pos.y, BMax.x - pViewport->Pos.x, BMax.y - pViewport->Pos.y };

                const bool bHot     = S.m_Hot == i;
                const bool bPressed = bHot && S.m_Pressed == i;
                ImU32      Glyph    = TextBright;
                if (i == BUTTON_CLOSE && bHot)
                {
                    DL.AddRectFilled(BMin, BMax, bPressed ? details::Color(0x94, 0x1F, 0x14) : details::Color(0xC4, 0x2B, 0x1C));
                    Glyph = IM_COL32_WHITE;
                }
                else if (bHot) DL.AddRectFilled(BMin, BMax, details::Color(0xFF, 0xFF, 0xFF, bPressed ? 16 : 26));

                const char*  pGlyph = (i == BUTTON_MAXIMIZE && bMaximized) ? RestoreGlyph : Glyphs[i];
                const ImVec2 GSize  = pText->CalcTextSizeA(TextSize, FLT_MAX, 0, pGlyph);
                DL.AddText(pText, TextSize, ImVec2(ImFloor(BMin.x + (ButtonWidth - GSize.x) * 0.5f), ImFloor(MidY - GSize.y * 0.5f)), Glyph, pGlyph);
            }
        }

        //
        // The wordmark, in the middle of the window
        //
        constexpr float Tracking = 2.0f;
        const details::glyph_run Runs[] =
        {
            { "x",    bFocused ? details::Color(0x9C, 0xC8, 0xFF) : details::Color(0x7A, 0x8C, 0xA3), bFocused ? details::Color(0x3A, 0x79, 0xBB) : details::Color(0x4A, 0x5A, 0x6E) },
            { "LION", bFocused ? details::Color(0xFF, 0xFF, 0xFF) : details::Color(0xA0, 0xA0, 0xA0), bFocused ? details::Color(0xB4, 0xB4, 0xB4) : details::Color(0x78, 0x78, 0x78) },
        };
        const float  MarkWidth = details::RunWidth(pLarge, LargeSize, Runs, IM_ARRAYSIZE(Runs), Tracking);
        const ImVec2 MarkPos(ImFloor(Min.x + (Width - MarkWidth) * 0.5f), ImFloor(MidY - LargeSize * 0.5f));
        details::DrawWordmark(DL, pLarge, LargeSize, MarkPos, Runs, IM_ARRAYSIZE(Runs), Tracking);

        //
        // The frame rate, right of the wordmark: the number (a fixed width, so it does not shake) and its last seconds
        //
        {
            constexpr float GraphWidth  = fps_history::count_v;
            const float     GraphHeight = ImFloor(Height * 0.5f);
            const float     Fps         = S.m_Fps.Current();
            char            Number[16];
            std::snprintf(Number, sizeof(Number), "%d", static_cast<int>(Fps + 0.5f));
            const float NumberWidth = pText->CalcTextSizeA(TextSize, FLT_MAX, 0, "000").x;
            const float LabelWidth  = pText->CalcTextSizeA(TextSize, FLT_MAX, 0, " FPS").x;
            const float X0          = MarkPos.x + MarkWidth + 20.0f;
            const float X1          = X0 + NumberWidth + LabelWidth + 8.0f + GraphWidth;
            if (X1 + 12.0f < ButtonsX)                                         // a narrow window: no room for it before the buttons
            {
                const float TextY = ImFloor(MidY - TextSize * 0.5f);
                const float NumW  = pText->CalcTextSizeA(TextSize, FLT_MAX, 0, Number).x;
                DL.AddText(pText, TextSize, ImVec2(X0 + NumberWidth - NumW, TextY), S.m_Fps.m_Filled ? details::FpsColor(Fps) : TextDim, Number);
                DL.AddText(pText, TextSize, ImVec2(X0 + NumberWidth, TextY), TextDim, " FPS");
                const ImVec2 GMin(X0 + NumberWidth + LabelWidth + 8.0f, ImFloor(MidY - GraphHeight * 0.5f));
                details::DrawFpsGraph(DL, S.m_Fps, GMin, ImVec2(GMin.x + GraphWidth, GMin.y + GraphHeight));
            }
        }

        //
        // "Project: <project>", left; cut short before it reaches the wordmark
        //
        {
            const float TextY = ImFloor(MidY - TextSize * 0.5f);
            const float X0    = Min.x + 10.0f;
            const float IconSize = ImFloor(ImMin(Height - 6.0f, 24.0f));
            const float TextX = pBrandIcon ? X0 + IconSize + 8.0f : Min.x + 12.0f;
            if (pBrandIcon)
            {
                const ImVec2 IconMin(ImFloor(X0), ImFloor(MidY - IconSize * 0.5f));
                const ImVec2 IconMax(IconMin.x + IconSize, IconMin.y + IconSize);
                DL.AddImage((ImTextureRef)(void*)pBrandIcon, IconMin, IconMax, ImVec2(0, 0), ImVec2(1, 1));
            }
            DL.PushClipRect(ImVec2(TextX, Min.y), ImVec2(ImMax(TextX, MarkPos.x - 16.0f), Min.y + Height), true);
            DL.AddText(pText, TextSize, ImVec2(TextX, TextY), TextDim, "Project:");
            const float Prefix = pText->CalcTextSizeA(TextSize, FLT_MAX, 0, "Project: ").x;
            DL.AddText(pText, TextSize, ImVec2(TextX + Prefix, TextY), TextBright, S.m_ProjectName.c_str());
            DL.PopClipRect();
        }

        S.m_Height = Height;

        //
        // The ImGui windows in front of the bar that take the mouse (popups, floating panels moved over it): there the mouse is ImGui's, not the caption's.
        // Their rectangles as of now - at worst a frame old for the ones not drawn yet this frame.
        //
        S.m_Holes.clear();
        {
            ImGuiContext& G = *ImGui::GetCurrentContext();
            bool bAbove = false;
            for (ImGuiWindow* pW : G.Windows)
            {
                if (pW == pBar) { bAbove = true; continue; }
                if (!bAbove || !(pW->Active || pW->WasActive) || pW->Hidden || pW->Viewport != pBar->Viewport) continue;
                if (pW->Flags & ImGuiWindowFlags_NoMouseInputs) continue;              // a tooltip, a toast: the mouse goes through them anyway
                if (pW->Pos.y >= Min.y + Height || pW->Pos.y + pW->Size.y <= Min.y) continue;
                S.m_Holes.push_back({ pW->Pos.x - pViewport->Pos.x, pW->Pos.y - pViewport->Pos.y, pW->Pos.x + pW->Size.x - pViewport->Pos.x, pW->Pos.y + pW->Size.y - pViewport->Pos.y });
            }
        }

        ImGui::End();
    }
}
