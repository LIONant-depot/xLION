#ifndef XEDITOR_FRAME_RECORDER_H
#define XEDITOR_FRAME_RECORDER_H
#pragma once

// A video of a preview, for any editor's viewport (the Animation Package editor's "Render video" first): one video frame per editor frame.
// Each frame the editor asks Frame() which frame to show, sets its preview to that time (paused) and draws its view; then Capture() asks the
// window for the back buffer at this frame's page flip (xgpu::window::Screenshot). The next Frame() crops the view's rectangle out of it and
// writes it as frame_NNNN.png; after the last one ffmpeg (when it is on the PATH or winget's links) encodes them, started on its own (the
// editor does not wait). The panel must be in the main window (a floating OS window is another swapchain) and stay where it is while it records.
#include "dependencies/xGPU/source/xgpu.h"
#include "dependencies/xbmp_tools/src/xbmp_tools.h"
#include "dependencies/imgui/imgui.h"
#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <format>
#include <string>
#include <vector>
#ifdef _WIN32
#include <process.h>        // _wspawnv: ffmpeg started on its own (no windows.h in a header: its macros break the compilers)
#endif

namespace xeditor
{
    struct frame_recorder
    {
        std::filesystem::path       m_Folder;           // where the frames go (frame_0000.png ...)
        std::filesystem::path       m_Video;            // the video ffmpeg makes (empty: frames only)
        int                         m_nFrames   = 0;    // 0: not recording
        int                         m_Fps       = 30;
        int                         m_iShown    = 0;    // the frame drawn this editor frame
        int                         m_iAsked    = -1;   // the frame whose pixels the window fills at its flip (-1: none)
        bool                        m_bAsked    = false;
        std::vector<std::uint32_t>  m_Pixels;
        int                         m_W = 0, m_H = 0;
        int                         m_X0 = 0, m_Y0 = 0, m_CW = 0, m_CH = 0;    // the view's rectangle in the back buffer's pixels
        std::string                 m_Result;           // the last run's outcome (shown and logged by the editor)

        bool Running(void) const noexcept { return m_nFrames > 0; }

        void Start(const std::filesystem::path& Folder, const std::filesystem::path& Video, int nFrames, int Fps) noexcept
        {
            std::error_code Ec;
            std::filesystem::remove_all(Folder, Ec);
            std::filesystem::create_directories(Folder, Ec);
            m_Folder = Folder; m_Video = Video; m_nFrames = std::max(1, nFrames); m_Fps = std::max(1, Fps);
            m_iShown = 0; m_iAsked = -1; m_bAsked = false; m_Result.clear();
        }
        void Cancel(void) noexcept { if (Running()) { m_Result = std::format("Render video: cancelled at frame {} of {}", m_iShown, m_nFrames); m_nFrames = 0; } }

        // Before drawing the view: the frame to show now (its time is Index / Fps), or -1 when not recording. Writes the frame read back at the
        // last flip; after the last one, encodes and stops (m_Result says how it went).
        int Frame(void) noexcept
        {
            if (!Running()) return -1;
            if (m_bAsked && m_iAsked >= 0 && !m_Pixels.empty())         // (the flip after Capture filled m_Pixels)
            {
                Write(m_iAsked);
                m_bAsked = false; m_Pixels.clear();
                m_iShown = m_iAsked + 1;
                if (m_iShown >= m_nFrames) { Finish(); return -1; }
            }
            return m_iShown;
        }

        // After drawing the view (its screen rectangle, ImGui coordinates): the window keeps this frame's back buffer at its flip.
        void Capture(xgpu::window& Window, const ImVec2& Min, const ImVec2& Size) noexcept
        {
            if (!Running() || m_bAsked) return;
            const ImVec2 Org = ImGui::GetMainViewport()->Pos, Scale = ImGui::GetIO().DisplayFramebufferScale;
            m_X0 = int((Min.x - Org.x) * Scale.x); m_Y0 = int((Min.y - Org.y) * Scale.y);
            m_CW = int(Size.x * Scale.x) & ~1;  m_CH = int(Size.y * Scale.y) & ~1;      // (even: the encoder's 4:2:0 wants it)
            m_Pixels.clear();
            if (m_CW < 2 || m_CH < 2 || !Window.Screenshot(m_Pixels, m_W, m_H)) { m_Result = "Render video: the window could not be read back"; m_nFrames = 0; return; }
            m_bAsked = true; m_iAsked = m_iShown;
        }

    private:
        void Write(int Index) noexcept
        {
            const int X0 = std::clamp(m_X0, 0, std::max(0, m_W - 2)), Y0 = std::clamp(m_Y0, 0, std::max(0, m_H - 2));
            const int CW = std::min(m_CW, m_W - X0) & ~1, CH = std::min(m_CH, m_H - Y0) & ~1;
            if (CW < 2 || CH < 2 || m_Pixels.size() < std::size_t(m_W) * m_H) return;
            // an xbitmap of raw pixels starts with the offset of its first mip (as the Level editor's CaptureWindow writes them); opaque alpha
            std::vector<std::uint32_t> Padded(1 + std::size_t(CW) * CH);
            Padded[0] = sizeof(xbitmap::mip);
            for (int y = 0; y < CH; ++y)
                for (int x = 0; x < CW; ++x) Padded[1 + std::size_t(y) * CW + x] = m_Pixels[std::size_t(Y0 + y) * m_W + (X0 + x)] | 0xFF000000u;
            xbitmap Bmp;
            Bmp.setup(CW, CH, xbitmap::format::B8G8R8A8, std::uint64_t(CW) * CH * sizeof(std::uint32_t), std::as_writable_bytes(std::span(Padded)), false, 1, 1);
            (void)xbmp::tools::writers::SaveSTDImage((m_Folder / std::format("frame_{:04}.png", Index)).wstring(), Bmp);
        }

        void Finish(void) noexcept
        {
            const int n = m_nFrames; m_nFrames = 0;
            m_Result = std::format("Render video: {} frames at {} fps in {}", n, m_Fps, m_Folder.string());
            if (m_Video.empty()) return;
#ifdef _WIN32
            // ffmpeg on the PATH, else winget's link folder; none: the frames stay (the result says so)
            std::filesystem::path Exe = L"ffmpeg.exe";
            bool bOnPath = false;
            if (const wchar_t* pPath = _wgetenv(L"PATH"))
                for (std::wstring_view Rest(pPath); !Rest.empty() && !bOnPath; )
                {
                    const auto Cut = Rest.find(L';');
                    const std::filesystem::path Dir(Rest.substr(0, Cut));
                    std::error_code Ec;
                    if (!Dir.empty() && std::filesystem::exists(Dir / L"ffmpeg.exe", Ec)) { Exe = Dir / L"ffmpeg.exe"; bOnPath = true; }
                    Rest = Cut == std::wstring_view::npos ? std::wstring_view{} : Rest.substr(Cut + 1);
                }
            if (!bOnPath)
            {
                const wchar_t* pLocal = _wgetenv(L"LOCALAPPDATA");
                std::error_code Ec;
                Exe = pLocal ? std::filesystem::path(pLocal) / L"Microsoft" / L"WinGet" / L"Links" / L"ffmpeg.exe" : std::filesystem::path{};
                if (Exe.empty() || !std::filesystem::exists(Exe, Ec)) { m_Result += " (ffmpeg not found: no video encoded)"; return; }
            }
            const std::wstring Fps = std::to_wstring(m_Fps), In = L"\"" + (m_Folder / L"frame_%04d.png").wstring() + L"\"", Out = L"\"" + m_Video.wstring() + L"\"", Prog = L"\"" + Exe.wstring() + L"\"";
            const wchar_t* Args[] = { Prog.c_str(), L"-y", L"-loglevel", L"error", L"-framerate", Fps.c_str(), L"-i", In.c_str(), L"-c:v", L"libx264", L"-pix_fmt", L"yuv420p", L"-crf", L"18", Out.c_str(), nullptr };
            if (_wspawnv(_P_NOWAIT, Exe.c_str(), Args) != -1) m_Result += " -> encoding " + m_Video.string();
            else m_Result += " (ffmpeg did not start: no video encoded)";
#else
            m_Result += " (encode with ffmpeg: frame_%04d.png)";       // ponytail: Linux encodes by hand until someone needs the button there
#endif
        }
    };
}
#endif
