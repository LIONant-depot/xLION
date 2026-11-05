#ifndef LevelEditor_COMMANDS_RESOURCE_EDITORS_H
#define LevelEditor_COMMANDS_RESOURCE_EDITORS_H
#pragma once

// LevelEditor hosts the resource editors of the plugins (Texture, Static Geom, ...): each one is a window with its own document and undo system,
// kept in xeditor::open_resource_editors. Including a plugin's editor header registers its factory. Open editors are also listed in
// xeditor::host, so `list` and Name\Command reach them like the Level; the two commands below are the guid-addressed way in.

#include "plugins/xtexture.plugin/source/Editor/xtexture_editor.h"
#include "plugins/xgeom_static.plugin/source/Editor/xgeom_static_editor.h"
#include "plugins/xmaterial_instance.plugin/source/Editor/xmaterial_instance_editor.h"
#include "plugins/xmaterial.plugin/source/Editor/xmaterial_editor.h"
#include "plugins/xfont.plugin/source/Editor/xfont_editor.h"
#include "plugins/xanim_package.plugin/source/Editor/xanim_package_editor.h"
#include "plugins/xgeom_skin.plugin/source/Editor/xgeom_skin_editor.h"
#include "plugins/xskeleton.plugin/source/Editor/xskeleton_editor.h"
#include "plugins/xPhysicsMaterial.plugin/source/Editor/xphysics_material_editor.h"
#include "plugins/xscript_module.plugin/source/Editor/xscript_module_editor.h"
#include "plugins/xtexture.plugin/source/xtexture_xgpu_rsc_loader.h"       // (xtexture_residency: TextureResidency)
#include "plugins/xgeom_static.plugin/source/xgeom_static_xgpu_rsc_loader.h"   // (xgeom_static_residency: GeomResidency)
#include "xprofile.h"                                                       // (Profiler)
#include <algorithm>
#include <cstdio>
#include <format>
#include "editor/xprofile_tab.h"                                            // (the drawer's Profiler tab)
#include "plugins/xgame.plugin/source/Editor/xgame_editor.h"
#include "plugins/xlevel.plugin/source/Editor/xlevel_command_context.h"
#include "dependencies/xeditor/include/xeditor/host.h"
#include "source/Editors/LevelEditor/extensions/command_console/LevelEditor_CommandConsolePipe.h"

namespace level_editor
{
    // A picture of the whole window, for whoever drives the editor by commands and wants to see it. The capture happens when the next frame is
    // presented: the app calls BeforeFlip and AfterFlip around the page flip.
    struct window_capture
    {
        bool                        m_bPending   = false;       // a capture was asked for
        bool                        m_bRequested = false;       // the window was told to capture this frame
        std::wstring                m_Path;
        std::vector<std::uint32_t>  m_Pixels;
        int                         m_Width = 0, m_Height = 0;

        void BeforeFlip(xgpu::window& Window) noexcept
        {
            if (m_bPending && !m_bRequested) m_bRequested = Window.Screenshot(m_Pixels, m_Width, m_Height);
        }

        // The file appears complete or not at all: it is written under a temporary name and renamed
        void AfterFlip() noexcept
        {
            if (!m_bRequested) return;
            m_bPending = m_bRequested = false;
            if (m_Width <= 0 || m_Height <= 0 || m_Pixels.size() < static_cast<std::size_t>(m_Width) * m_Height) return;

            // An xbitmap of raw pixels starts with the offset of its first mip: one slot ahead of the pixels. The alpha of a back buffer is
            // whatever the pipeline left there, so it is made opaque.
            std::vector<std::uint32_t> Padded(1 + static_cast<std::size_t>(m_Width) * m_Height);
            Padded[0] = sizeof(xbitmap::mip);
            for (std::size_t i = 0; i < static_cast<std::size_t>(m_Width) * m_Height; ++i) Padded[1 + i] = m_Pixels[i] | 0xFF000000u;

            xbitmap Bitmap;
            Bitmap.setup(m_Width, m_Height, xbitmap::format::B8G8R8A8, static_cast<std::uint64_t>(m_Width) * m_Height * sizeof(std::uint32_t), std::as_writable_bytes(std::span(Padded)), false, 1, 1);

            std::filesystem::path Final(m_Path);
            std::filesystem::path Temp = Final;
            Temp.replace_extension(L".part" + Final.extension().wstring());
            if (xbmp::tools::writers::SaveSTDImage(Temp.wstring(), Bitmap)) return;
            std::error_code Ec;
            std::filesystem::rename(Temp, Final, Ec);
            if (Ec) { std::filesystem::remove(Final, Ec); std::filesystem::rename(Temp, Final, Ec); }
        }
    };

    inline window_capture g_WindowCapture;

    // "Is there noise, how much, where?" (NoiseCheck): consecutive pictures of the window as it is shown, tone mapping, TAA and all, with the camera still. A pixel's noise is the RMS of its
    // frame to frame change / sqrt 2 (a noise's standard deviation, out of 255 of display luminance): a slow drift over seconds barely counts. Writes <File> (where and how much, over a dim copy of
    // the picture) and <File>.txt (the numbers and the worst tiles). ponytail: a noise a frame repeats (fixed rays, a static pattern) isn't seen: that takes comparing against a reference
    struct window_noise
    {
        bool                        m_bActive = false, m_bRequested = false;
        int                         m_Left = 0, m_N = 0, m_Width = 0, m_Height = 0, m_X = 0, m_Y = 0, m_W = 0, m_H = 0;
        std::wstring                m_Path;
        std::vector<std::uint32_t>  m_Pixels;
        std::vector<float>          m_Prev, m_Sum;

        void Start(std::wstring Path, int Frames, int X, int Y, int W, int H) noexcept
        {
            m_Path = std::move(Path); m_Left = std::max(Frames, 2); m_N = 0; m_X = X; m_Y = Y; m_W = W; m_H = H; m_Prev.clear(); m_Sum.clear(); m_bRequested = false; m_bActive = true;
        }
        void BeforeFlip(xgpu::window& Window) noexcept
        {
            if (m_bActive && !m_bRequested) m_bRequested = Window.Screenshot(m_Pixels, m_Width, m_Height);
        }
        void AfterFlip() noexcept
        {
            if (!m_bRequested) return;
            m_bRequested = false;
            const std::size_t n = static_cast<std::size_t>(m_Width) * m_Height;
            if (m_Width <= 0 || m_Height <= 0 || m_Pixels.size() < n) return;
            if (m_Prev.size() != n) { m_Prev.assign(n, 0.0f); m_Sum.assign(n, 0.0f); m_N = 0; }
            for (std::size_t i = 0; i < n; ++i)
            {
                const std::uint32_t c = m_Pixels[i];
                const float L = 0.0722f * float(c & 255u) + 0.7152f * float((c >> 8) & 255u) + 0.2126f * float((c >> 16) & 255u);
                if (m_N > 0) { const float d = L - m_Prev[i]; m_Sum[i] += d * d; }
                m_Prev[i] = L;
            }
            ++m_N;
            if (--m_Left <= 0) { Finish(); m_bActive = false; }
        }
        void Finish() noexcept
        {
            const int X0 = std::clamp(m_X, 0, m_Width), Y0 = std::clamp(m_Y, 0, m_Height), X1 = m_W > 0 ? std::clamp(m_X + m_W, X0, m_Width) : m_Width, Y1 = m_H > 0 ? std::clamp(m_Y + m_H, Y0, m_Height) : m_Height;
            const float Div = 1.0f / (2.0f * float(std::max(m_N - 1, 1)));
            std::vector<float> Inside; Inside.reserve(std::size_t(X1 - X0) * (Y1 - Y0));
            std::vector<std::uint32_t> Out(1 + static_cast<std::size_t>(m_Width) * m_Height);
            Out[0] = sizeof(xbitmap::mip);
            constexpr int Tile = 64;
            struct tile { float m_Mean; int m_X, m_Y; };
            std::vector<float> TileSum(std::size_t((X1 - X0) / Tile + 1) * ((Y1 - Y0) / Tile + 1), 0.0f);
            const int TilesW = (X1 - X0) / Tile + 1;
            for (int y = 0; y < m_Height; ++y) for (int x = 0; x < m_Width; ++x)
            {
                const std::size_t i = std::size_t(y) * m_Width + x;
                const float S = std::sqrt(m_Sum[i] * Div), Bg = m_Prev[i] * 0.3f, T = std::clamp(S / 16.0f, 0.0f, 1.0f);     // (16 of 255 and over: full red)
                const bool bIn = x >= X0 && x < X1 && y >= Y0 && y < Y1;
                if (bIn) { Inside.push_back(S); TileSum[std::size_t((y - Y0) / Tile) * TilesW + (x - X0) / Tile] += S; }
                const float R = Bg + T * 255.0f, G = Bg + std::min(T * 2.0f, 1.0f) * (1.0f - T) * 255.0f, Bl = Bg;      // (dark, then green, then red)
                Out[1 + i] = 0xFF000000u | (std::uint32_t(std::min(R, 255.0f)) << 16) | (std::uint32_t(std::min(G, 255.0f)) << 8) | std::uint32_t(std::min(Bl, 255.0f));
            }
            xbitmap Bitmap;
            Bitmap.setup(m_Width, m_Height, xbitmap::format::B8G8R8A8, static_cast<std::uint64_t>(m_Width) * m_Height * sizeof(std::uint32_t), std::as_writable_bytes(std::span(Out)), false, 1, 1);
            std::filesystem::path Final(m_Path), Temp = Final;
            Temp.replace_extension(L".part" + Final.extension().wstring());
            std::error_code Ec;
            if (!xbmp::tools::writers::SaveSTDImage(Temp.wstring(), Bitmap)) { std::filesystem::rename(Temp, Final, Ec); if (Ec) { std::filesystem::remove(Final, Ec); std::filesystem::rename(Temp, Final, Ec); } }

            double Mean = 0.0; std::size_t Over2 = 0, Over4 = 0, Over8 = 0;
            for (const float v : Inside) { Mean += v; Over2 += v > 2.0f; Over4 += v > 4.0f; Over8 += v > 8.0f; }
            const double Count = double(std::max<std::size_t>(Inside.size(), 1)); Mean /= Count;
            float P95 = 0.0f;
            if (!Inside.empty()) { const auto At = Inside.begin() + std::ptrdiff_t(Inside.size() * 95 / 100); std::nth_element(Inside.begin(), At, Inside.end()); P95 = *At; }
            std::vector<tile> Worst;
            for (std::size_t t = 0; t < TileSum.size(); ++t) Worst.push_back({ TileSum[t] / float(Tile * Tile), X0 + int(t % TilesW) * Tile, Y0 + int(t / TilesW) * Tile });
            const std::size_t nTop = std::min<std::size_t>(Worst.size(), 8);
            std::partial_sort(Worst.begin(), Worst.begin() + std::ptrdiff_t(nTop), Worst.end(), [](const tile& a, const tile& b) { return a.m_Mean > b.m_Mean; });
            const char* pVerdict = 100.0 * Over8 / Count > 0.1 ? "NOISY" : 100.0 * Over4 / Count > 1.0 ? "some noise" : "clean";
            std::string Text = std::format("NOISE {}: {} frames, mean {:.2f}, p95 {:.2f} of 255; pixels over 2: {:.2f} %, over 4: {:.2f} %, over 8: {:.3f} %\nworst tiles ({} px), mean, x, y:\n", pVerdict, m_N, Mean, P95, 100.0 * Over2 / Count, 100.0 * Over4 / Count, 100.0 * Over8 / Count, Tile);
            for (std::size_t t = 0; t < nTop; ++t) Text += std::format("{:.2f} {} {}\n", Worst[t].m_Mean, Worst[t].m_X, Worst[t].m_Y);
            if (std::FILE* f = _wfopen((m_Path + L".txt").c_str(), L"wb")) { std::fwrite(Text.data(), 1, Text.size(), f); std::fclose(f); }
            std::printf("%s", Text.c_str()); std::fflush(stdout);
            m_Sum.clear(); m_Prev.clear();
        }
    };

    inline window_noise g_WindowNoise;
}

namespace level_editor::commands
{
    inline xeditor::open_resource_editors* FindResourceEditors() noexcept
    {
        auto* pHost = xeditor::host::current();
        return pHost ? pHost->find<xeditor::open_resource_editors>() : nullptr;
    }

    // Shows the file a component or a system is defined in: the module's editor is opened (or brought to the front) and its viewer shows the file; a type of the engine has its file handed
    // to the system. What a click on the module tag of a component header, or "Open ..." of the System Registry's menu, does.
    inline bool OpenTypeSource(const xscene::type_source& Source) noexcept
    {
        if (Source.m_Path.empty()) return false;
        if (Source.m_Module)
            if (auto* pEditors = FindResourceEditors())
            {
                const xresource::full_guid Asset{ xresource::instance_guid{ Source.m_Module }, xscript::module::type_guid_v };
                if (const auto Library = xeditor::open_resource_editors::FindLibraryOf(Asset); !Library.empty()) pEditors->Open(Asset, Library);
            }
        xeditor::OpenRef(xlog::ref{ xlog::ref::type::File, Source.m_Path, 0, 0, 0, 0 });
        return true;
    }
    inline const bool g_TypeSourceOpener = (xscene::g_OpenTypeSource = &OpenTypeSource, true);

    // The same file in the Visual Studio of the active Level's game project (see xlevel_visual_studio.h).
    inline std::string OpenTypeSourceInVisualStudio(const xscene::type_source& Source, bool bDryRun) noexcept
    {
        auto* pLevel = xlevel::FindLevelContext();
        if (!pLevel) return "no Level is open";
        if (Source.m_Path.empty()) return "the type has no file";
        return xlevel::RequestOpenFileInVisualStudio(*pLevel, std::filesystem::path(Source.m_Path), bDryRun);
    }
    inline const bool g_TypeSourceVisualStudioOpener = (xscene::g_OpenTypeSourceInVisualStudio = &OpenTypeSourceInVisualStudio, true);

    // OpenTypeSource -Guid hex16 [-System true]: the same, by the guid of the component (or of the system, with -System true): what the AI and the tests use instead of the mouse.
    struct open_type_source_cmd : xlevel::commands::level_query_command
    {
        open_type_source_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "OpenTypeSource", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Shows the file a component (or, with -System true, a system) is defined in: the module's editor opens at it, or with -In VisualStudio the Visual Studio of the Level's game project (-DryRun true only says what it would do). Usage: OpenTypeSource -Guid hexguid [-System true] [-In Module|VisualStudio] [-DryRun true]"; }
        void RegisterArguments() noexcept override
        {
            m_hGuid   = m_Parser.addOption("Guid",   "The guid of the component or the system, 16 hex digits", true, 1);
            m_hSystem = m_Parser.addOption("System", "true: it is a system", false, 1);
            m_hIn     = m_Parser.addOption("In",     "Module (default): the module's editor; VisualStudio: the Visual Studio of the game project", false, 1);
            m_hDryRun = m_Parser.addOption("DryRun", "true: only say what opening in Visual Studio would do", false, 1);
        }
        std::string Query() noexcept override
        {
            auto GuidArg = m_Parser.getOptionArgAs<std::string>(m_hGuid, 0);
            if (std::holds_alternative<xerr>(GuidArg)) return "OpenTypeSource: bad arguments";
            const std::uint64_t Guid = std::strtoull(std::get<std::string>(GuidArg).c_str(), nullptr, 16);
            auto SystemArg = m_Parser.getOptionArgAs<std::string>(m_hSystem, 0);
            const bool bSystem = !std::holds_alternative<xerr>(SystemArg) && std::get<std::string>(SystemArg) == "true";

            const auto Source = LevelContext().Display().SourceOf(bSystem, Guid);
            if (!Source.m_bKnown)   return "OpenTypeSource: nothing is known about where types come from (is Game.dll loaded, and recent enough?)";
            if (Source.m_bBuiltIn)  return std::format("OpenTypeSource: {:016X} is built in (the engine's or the editor's own): no module defines it", Guid);
            auto InArg = m_Parser.getOptionArgAs<std::string>(m_hIn, 0);
            const std::string In = std::holds_alternative<xerr>(InArg) ? std::string("Module") : std::get<std::string>(InArg);
            if (In == "VisualStudio")
            {
                auto DryArg = m_Parser.getOptionArgAs<std::string>(m_hDryRun, 0);
                const bool bDryRun = !std::holds_alternative<xerr>(DryArg) && (std::get<std::string>(DryArg) == "true" || std::get<std::string>(DryArg) == "1");
                return "OpenTypeSource: " + OpenTypeSourceInVisualStudio(Source, bDryRun);
            }
            if (In != "Module") return "OpenTypeSource: -In is Module or VisualStudio";
            if (!OpenTypeSource(Source)) return "OpenTypeSource: the type has no file";
            return std::format("OpenTypeSource: ok\nModule={}\nFile={}\nPath={}", Source.m_ModuleName, Source.m_File, Source.m_Path);
        }
        xcmdline::parser::handle m_hGuid, m_hSystem, m_hIn, m_hDryRun;
    };

    struct open_resource_editor_cmd : xlevel::commands::level_query_command
    {
        open_resource_editor_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "OpenResourceEditor", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Opens the editor of a resource (Texture, GeomStatic, ...) in its own dock-isolated window, or focuses it when it is already open. Usage: OpenResourceEditor -Asset assetguid [-Library hexguid]"; }
        void RegisterArguments() noexcept override
        {
            m_hLibrary = m_Parser.addOption("Library", "Library instance guid, 16 hex digits (default: the library that has the resource)", false, 1);
            m_hAsset   = m_Parser.addOption("Asset",   "Resource guid, 32 hex digits",                                                       true,  1);
        }
        std::string Query() noexcept override
        {
            auto AssetArg = m_Parser.getOptionArgAs<std::string>(m_hAsset, 0);
            if (std::holds_alternative<xerr>(AssetArg)) return "OpenResourceEditor: bad arguments";

            auto* pEditors = FindResourceEditors();
            if (!pEditors) return "OpenResourceEditor: no editor host";

            const auto AssetGuid = xresource_editor::commands::ParseAssetGuid(std::get<std::string>(AssetArg));
            if (!xeditor::open_resource_editors::HasEditorFor(AssetGuid.m_Type)) return "OpenResourceEditor: this resource type has no editor";

            auto LibraryGuid = xeditor::open_resource_editors::FindLibraryOf(AssetGuid);
            if (m_Parser.hasOption(m_hLibrary))
            {
                auto LibraryArg = m_Parser.getOptionArgAs<std::string>(m_hLibrary, 0);
                if (std::holds_alternative<xerr>(LibraryArg)) return "OpenResourceEditor: bad arguments";
                LibraryGuid = xresource_editor::commands::ParseLibraryGuid(std::get<std::string>(LibraryArg));
            }
            if (LibraryGuid.empty()) return "OpenResourceEditor: no open library has that resource";

            auto* pEditor = pEditors->Open(AssetGuid, LibraryGuid);
            return pEditor && pEditor->isLoaded() ? "" : "OpenResourceEditor: failed to load the descriptor";
        }
        xcmdline::parser::handle m_hLibrary, m_hAsset;
    };

    struct capture_window_cmd : xlevel::commands::level_query_command
    {
        capture_window_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "CaptureWindow", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Saves a picture of the whole editor window (png, bmp, tga or jpg by the extension). The file appears when the next frame is presented. Usage: CaptureWindow -File path"; }
        void RegisterArguments() noexcept override { m_hFile = m_Parser.addOption("File", "Where to write the picture", true, 1); }
        std::string Query() noexcept override
        {
            auto FileArg = m_Parser.getOptionArgAs<std::string>(m_hFile, 0);
            if (std::holds_alternative<xerr>(FileArg)) return "CaptureWindow: bad arguments";
            const std::filesystem::path Path = xstrtool::To(std::get<std::string>(FileArg));
            if (Path.extension().empty()) return "CaptureWindow: the file needs an extension (png, bmp, tga or jpg)";
            if (g_WindowCapture.m_bPending) return "CaptureWindow: a capture is already waiting for the next frame";
            std::error_code Ec;
            if (Path.has_parent_path()) std::filesystem::create_directories(Path.parent_path(), Ec);
            std::filesystem::remove(Path, Ec);
            g_WindowCapture.m_Path     = Path.wstring();
            g_WindowCapture.m_bPending = true;
            return "CaptureWindow: queued, the file appears when the next frame is presented";
        }
        xcmdline::parser::handle m_hFile;
    };

    struct noise_check_cmd : xlevel::commands::level_query_command
    {
        noise_check_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "NoiseCheck", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Is there noise, how much, where? Keep the camera still. Over -Frames n frames (default 32) writes -File x.png (where and how much: green about 8 of 255, red 16 and over, over a dim copy of the picture) and x.png.txt (a verdict, mean, p95, how many pixels over 2, 4, 8, the worst tiles). -Rect x,y,w,h: only that part counts (the 3D view: panels' text changes). A noise that repeats every frame isn't seen. Usage: NoiseCheck -File x.png [-Frames n] [-Rect x,y,w,h]"; }
        void RegisterArguments() noexcept override
        {
            m_hFile   = m_Parser.addOption("File", "The picture of the noise; its numbers in the same name + .txt", true, 1);
            m_hFrames = m_Parser.addOption("Frames", "How many frames (default 32)", false, 1);
            m_hRect   = m_Parser.addOption("Rect", "x,y,w,h: the part that counts", false, 1);
        }
        std::string Query() noexcept override
        {
            auto FileArg = m_Parser.getOptionArgAs<std::string>(m_hFile, 0);
            if (std::holds_alternative<xerr>(FileArg)) return "NoiseCheck: bad arguments";
            if (g_WindowNoise.m_bActive) return "NoiseCheck: one is already running";
            const std::filesystem::path Path = xstrtool::To(std::get<std::string>(FileArg));
            if (Path.extension().empty()) return "NoiseCheck: the file needs an extension (png)";
            int Frames = 32, X = 0, Y = 0, W = 0, H = 0;
            if (auto A = m_Parser.getOptionArgAs<std::string>(m_hFrames, 0); !std::holds_alternative<xerr>(A)) Frames = std::atoi(std::get<std::string>(A).c_str());
            if (auto A = m_Parser.getOptionArgAs<std::string>(m_hRect, 0); !std::holds_alternative<xerr>(A)) std::sscanf(std::get<std::string>(A).c_str(), "%d,%d,%d,%d", &X, &Y, &W, &H);
            std::error_code Ec;
            if (Path.has_parent_path()) std::filesystem::create_directories(Path.parent_path(), Ec);
            std::filesystem::remove(Path, Ec); std::filesystem::remove(Path.wstring() + L".txt", Ec);
            g_WindowNoise.Start(Path.wstring(), Frames, X, Y, W, H);
            return "NoiseCheck: running, the numbers appear in the file's .txt";
        }
        xcmdline::parser::handle m_hFile, m_hFrames, m_hRect;
    };

    // Profiler: the profiler (xprofile, Tracy's client) on and off, and its state; a viewer (Tracy's, v0.14.1) connects to the editor once it is on
    struct profiler_cmd : xlevel::commands::level_query_command
    {
        profiler_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "Profiler", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override
        {
            return "The profiler (xprofile / Tracy). -Enable 1|0 records or stops (a Tracy viewer can connect while on). -Stats: the recorder's last frames - "
                   "frame mean/p95/max, the zones with the most time (ms per frame, calls per frame, mean, max), the plots (-Frames n window, default 120; "
                   "-Top k zones, default 25; -Filter text). -Capture file -Seconds s: Tracy's capture tool records this editor into a .tracy file in the "
                   "background (the reply returns at once). -Mark text: a line on the timeline. -Clear: empties the recorder. -Memory: the memory pools (kept "
                   "whether recording or not: VRAM's blocks and what is in them) - used, reserved, peak, free inside the regions, fragmentation; -Map n: "
                   "each region as n characters (# full, + partly used, . free); -Owners: the memory by owner (the resource whose load made it) and by "
                   "type, the most first (-Top k); -Filter text: only the pools whose name has it. -Show Metrics|Memory|VRAM|System RAM: opens "
                   "the drawer on the Profiler tab at that page. Without arguments: its state. "
                   "Usage: Profiler [-Enable 0|1] [-Clear] [-Mark text] [-Stats [-Frames n] [-Top k] [-Filter text]] [-Capture file [-Seconds s]] [-Memory [-Map n] [-Owners [-Top k]]] [-Show Metrics|Memory|VRAM|System RAM]";
        }
        void RegisterArguments() noexcept override
        {
            m_hEnable  = m_Parser.addOption("Enable", "1: record, 0: stop", false, 1);
            m_hStats   = m_Parser.addOption("Stats", "The recorder's numbers as text", false, 0);
            m_hFrames  = m_Parser.addOption("Frames", "Stats: the window in frames (default 120)", false, 1);
            m_hTop     = m_Parser.addOption("Top", "Stats: how many zones (default 25)", false, 1);
            m_hFilter  = m_Parser.addOption("Filter", "Stats: only the zones and plots whose name has this text", false, 1);
            m_hCapture = m_Parser.addOption("Capture", "A .tracy file Tracy's capture tool records into (in the background)", false, 1);
            m_hSeconds = m_Parser.addOption("Seconds", "Capture: how long (default 10)", false, 1);
            m_hMark    = m_Parser.addOption("Mark", "A line on the timeline", false, 1);
            m_hClear   = m_Parser.addOption("Clear", "Empties the recorder", false, 0);
            m_hMemory  = m_Parser.addOption("Memory", "The memory pools as text", false, 0);
            m_hMap     = m_Parser.addOption("Map", "Memory: each region as this many characters", false, 1);
            m_hOwners  = m_Parser.addOption("Owners", "Memory: the memory by owner and by type", false, 0);
            m_hShow    = m_Parser.addOption("Show", "Opens the drawer on the Profiler tab at this page: Metrics or Memory", false, 1);
        }
        std::string Arg(xcmdline::parser::handle h, std::string Default = {}) noexcept
        {
            if (!m_Parser.hasOption(h)) return Default;
            auto A = m_Parser.getOptionArgAs<std::string>(h, 0);
            return std::holds_alternative<xerr>(A) ? Default : std::get<std::string>(A);
        }
        std::string Query() noexcept override
        {
        #if !(defined(XLION_PROFILE) && XLION_PROFILE)
            return "Profiler: not compiled in (XLION_PROFILE off)";
        #else
            std::string Out;
            if (m_Parser.hasOption(m_hEnable)) xprofile::Enable(Arg(m_hEnable, "1") != "0");
            if (m_Parser.hasOption(m_hClear))  xprofile::ClearRecorder();
            if (m_Parser.hasOption(m_hMark))   { const auto M = Arg(m_hMark); XPROFILE_MESSAGE(M.data(), M.size()); }
            if (m_Parser.hasOption(m_hCapture))
            {
                const auto File = Arg(m_hCapture); const int Seconds = std::atoi(Arg(m_hSeconds, "10").c_str());
                Out += xprofile::LaunchCapture(File.c_str(), Seconds) ? std::format("capturing {} s into {} (Tracy's capture tool, in the background)\n", Seconds, File)
                                                                      : "the capture did not start: Tracy's capture tool is not built (xprofile/build/tools/BuildTracyTools)\n";
            }
            Out += std::format("Profiler: {}, viewer {}", xprofile::isEnabled() ? "recording" : "off", xprofile::isConnected() ? "connected" : "not connected");
            if (m_Parser.hasOption(m_hMemory)) Out += MemoryText(Arg(m_hFilter), std::atoi(Arg(m_hMap, "0").c_str()), m_Parser.hasOption(m_hOwners) ? std::max(1, std::atoi(Arg(m_hTop, "25").c_str())) : 0);
            if (m_Parser.hasOption(m_hShow))
            {
                auto* pHost = xeditor::host::current();
                auto* pTab  = pHost ? pHost->find<xprofile::editor::tab>() : nullptr;
                if (!pTab) return Out + "\nShow: no Profiler tab in this editor";
                pTab->m_Select = Arg(m_hShow, "Metrics");
                xeditor::drawer& Drawer = pHost->drawer_for(xeditor::FocusedDrawerViewport()->ID);
                Drawer.m_bOpen = true;
                Drawer.m_ActiveTab = Drawer.m_RequestTab = 8;       // (xeditor's drawer: tab 8 is Profiler)
                Out += std::format("\nShow: the drawer opened on Profiler / {}", pTab->m_Select);
            }
            if (!m_Parser.hasOption(m_hStats)) return Out;

            // the recorder's window: frames, the zones with the most time, the plots
            xprofile::snapshot S;
            xprofile::Snapshot(std::max(1, std::atoi(Arg(m_hFrames, "120").c_str())), S);
            const int         Top    = std::max(1, std::atoi(Arg(m_hTop, "25").c_str()));
            const std::string Filter = Arg(m_hFilter);
            const auto Has = [&](const char* p) { return Filter.empty() || xprofile::editor::tab::Contains(p ? p : "", Filter.c_str()); };
            const double nFrames = std::max<std::size_t>(S.m_FrameMs.size(), 1);
            if (!S.m_FrameMs.empty())
            {
                auto F = S.m_FrameMs; std::sort(F.begin(), F.end());
                double Sum = 0; for (float v : F) Sum += v;
                Out += std::format("\nframes {}: mean {:.3f} ms, median {:.3f}, p95 {:.3f}, max {:.3f}; threads with zones {}", F.size(), Sum / F.size(), F[F.size() / 2], F[std::min(F.size() - 1, F.size() * 95 / 100)], F.back(), S.m_nThreads);
            }
            else Out += "\nno frames marked in the window (the last second's zones)";
            Out += std::format("\n{:<44} {:>10} {:>9} {:>10} {:>10}", "zone", "ms/frame", "calls/fr", "mean ms", "max ms");
            int n = 0;
            for (const auto& Z : S.m_Zones)
            {
                const char* pName = Z.m_pWhere && Z.m_pWhere->name ? Z.m_pWhere->name : "?";
                if (!Has(pName)) continue;
                if (n++ == Top) break;
                Out += std::format("\n{:<44} {:>10.3f} {:>9.1f} {:>10.3f} {:>10.3f}", std::string(pName).substr(0, 44), Z.m_TotalMs / nFrames, Z.m_Count / nFrames, Z.m_TotalMs / std::max<std::uint32_t>(Z.m_Count, 1), Z.m_MaxMs);
            }
            for (const auto& P : S.m_Plots)
            {
                if (!Has(P.m_pName)) continue;
                Out += std::format("\nplot {}: now {:.2f}, range {:.2f} .. {:.2f}", P.m_pName, P.m_Last, P.m_Min, P.m_Max);
                if (P.m_Limit > 0) Out += std::format(", max {:.0f} ({:.1f}%)", P.m_Limit, 100.0 * P.m_Last / P.m_Limit);
            }
            return Out;
        #endif
        }
        xcmdline::parser::handle m_hEnable, m_hStats, m_hFrames, m_hTop, m_hFilter, m_hCapture, m_hSeconds, m_hMark, m_hClear, m_hMemory, m_hMap, m_hShow, m_hOwners;

    #if defined(XLION_PROFILE) && XLION_PROFILE
        // The memory pools: per pool its totals, per region its use, holes and fragmentation (the free space outside the largest hole) and,
        // with Width, a line of characters - each one Width-th of the region: # full, + partly used, . free
        static std::string MemoryText(const std::string& Filter, int Width, int TopOwners) noexcept
        {
            std::vector<xprofile::mem_pool> Pools;
            xprofile::MemSnapshot(Pools);
            constexpr double MB = 1.0 / (1024.0 * 1024.0);
            std::string Out;
            // the spaces as the driver sees them (the whole memory: its size, this process's budget and usage)
            std::vector<xprofile::mem_space> Spaces;
            xprofile::MemSpaces(Spaces);
            for (const auto& S : Spaces)
                Out += std::format("\nspace {}: {:.2f} GB in all, this process uses {:.2f} GB, its budget {:.2f} GB ({:.2f} GB free for it){}", S.m_pName, S.m_Size * MB / 1024,
                                   S.m_Usage * MB / 1024, S.m_Budget * MB / 1024, S.m_Budget > S.m_Usage ? (S.m_Budget - S.m_Usage) * MB / 1024 : 0.0, S.m_Usage ? "" : " (no usage from the driver)");
            std::vector<xprofile::mem_counter> Counters;
            xprofile::MemCounters(Counters);
            for (const auto& C : Counters) Out += std::format("\ncounter {}: {:.1f} MB in {} blocks", C.m_pName, C.m_Bytes * MB, C.m_Count);
            for (const auto& P : Pools)
            {
                if (!Filter.empty() && !xprofile::editor::tab::Contains(P.m_pName, Filter.c_str())) continue;
                std::uint64_t Free = 0;
                for (const auto& R : P.m_Regions) Free += R.m_Size - std::min(R.m_Used, R.m_Size);
                Out += std::format("\nmemory {}: {:.1f} MB used in {} allocations, {:.1f} MB reserved in {} regions, peak {:.1f} MB, free inside the regions {:.1f} MB",
                                   P.m_pName, P.m_Used * MB, P.m_nAllocs, P.m_Reserved * MB, P.m_Regions.size(), P.m_Peak * MB, Free * MB);
                for (const auto& R : P.m_Regions)
                {
                    const std::uint64_t RFree = R.m_Size - std::min(R.m_Used, R.m_Size);
                    int nHoles = 0; std::uint64_t End = 0;
                    for (const auto& A : R.m_Allocs) { nHoles += A.m_Offset > End; End = std::max(End, A.m_Offset + A.m_Size); }
                    nHoles += R.m_Size > End;
                    Out += std::format("\n  region {:>16x} {:7.1f} MB {:5.1f}% used, {:4} allocations, {:3} holes, largest {:6.2f} MB, fragmentation {:3.0f}%",
                                       R.m_Id, R.m_Size * MB, R.m_Size ? 100.0 * R.m_Used / R.m_Size : 0.0, R.m_Allocs.size(), nHoles, R.m_LargestFree * MB,
                                       RFree ? 100.0 * (1.0 - double(R.m_LargestFree) / double(RFree)) : 0.0);
                    if (Width <= 0 || R.m_Size == 0) continue;
                    std::vector<double> Cell(Width, 0.0);           // the bytes allocated in each character's range
                    const double Per = double(R.m_Size) / Width;
                    for (const auto& A : R.m_Allocs)
                        for (double a = double(A.m_Offset), b = double(A.m_Offset + A.m_Size); a < b;)
                        {
                            const int    c    = std::min(Width - 1, int(a / Per));
                            const double Next = std::min(b, (c + 1) * Per);
                            Cell[c] += Next - a; a = Next;
                        }
                    Out += "\n    |";
                    for (double v : Cell) Out += v >= Per * 0.999 ? '#' : v > 0 ? '+' : '.';
                    Out += '|';
                }
                if (TopOwners <= 0) continue;
                // by owner ("<type> <guid>": the resource whose load or replacement made it) and by its type
                std::map<std::string, std::pair<std::uint64_t, int>> ByOwner, ByType, ByWhat;
                for (const auto& R : P.m_Regions)
                    for (const auto& A : R.m_Allocs)
                    {
                        const std::string Owner = A.m_pOwner ? A.m_pOwner : "(no owner)";
                        auto& O = ByOwner[Owner]; O.first += A.m_Size; ++O.second;
                        auto& T = ByType[Owner[0] == '(' ? Owner : Owner.substr(0, Owner.find(' '))]; T.first += A.m_Size; ++T.second;
                        auto& W = ByWhat[A.m_pTag ? A.m_pTag : "?"]; W.first += A.m_Size; ++W.second;      // what it is (xGPU's setup name: "Shadows: atlas")
                    }
                const auto Sorted = [](const auto& M) { std::vector<std::pair<std::string, std::pair<std::uint64_t, int>>> V(M.begin(), M.end()); std::sort(V.begin(), V.end(), [](auto& a, auto& b) { return a.second.first > b.second.first; }); return V; };
                Out += "\nby what it is:";
                for (const auto& [Name, U] : Sorted(ByWhat)) Out += std::format("\n  {:<40} {:8.1f} MB in {} allocations", Name, U.first * MB, U.second);
                Out += "\nby type:";
                for (const auto& [Name, U] : Sorted(ByType)) Out += std::format("\n  {:<32} {:8.1f} MB in {} allocations", Name, U.first * MB, U.second);
                Out += std::format("\nby owner (the {} with the most):", TopOwners);
                int n = 0;
                for (const auto& [Name, U] : Sorted(ByOwner)) { if (n++ == TopOwners) break; Out += std::format("\n  {:<40} {:8.1f} MB in {} allocations", Name, U.first * MB, U.second); }
            }
            return Out.empty() ? "\nmemory: no pool reported" : Out;
        }
    #endif
    };

    // TextureResidency: scripted residency requests to the editor's textures (xtexture_residency; P3b of the texture pipeline - before any
    // automatic demand): which mips their images hold, top mip in each texture's own numbering (0: full size; clamped to its tail). The
    // textures move over the next frames (a new image each, in the background); the reply is where things stand now.
    struct texture_residency_cmd : xlevel::commands::level_query_command
    {
        texture_residency_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "TextureResidency", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Which mips the loaded textures keep: -TopMip n (0 the full size, 1 half, ... down to each texture's tail), for every texture or the one of -Asset; -BudgetMB m caps the big mips' memory (0: none). Without arguments: the state (bytes, textures moving). Usage: TextureResidency [-TopMip n] [-Asset guid] [-BudgetMB m]"; }
        void RegisterArguments() noexcept override
        {
            m_hTop    = m_Parser.addOption("TopMip", "The first mip kept (0: full size)", false, 1);
            m_hAsset  = m_Parser.addOption("Asset", "One texture's resource guid (32 hex digits); none: all", false, 1);
            m_hBudget = m_Parser.addOption("BudgetMB", "The big mips' memory budget in MB (0: none)", false, 1);
        }
        std::string Query() noexcept override
        {
            if (m_Parser.hasOption(m_hBudget))
            {
                auto B = m_Parser.getOptionArgAs<std::string>(m_hBudget, 0);
                if (std::holds_alternative<xerr>(B)) return "TextureResidency: bad -BudgetMB";
                xtexture_residency::setBudget(std::uint64_t(std::max(0, std::atoi(std::get<std::string>(B).c_str()))) << 20);
            }
            if (m_Parser.hasOption(m_hTop))
            {
                auto T = m_Parser.getOptionArgAs<std::string>(m_hTop, 0);
                if (std::holds_alternative<xerr>(T)) return "TextureResidency: bad -TopMip";
                const int Top = std::atoi(std::get<std::string>(T).c_str());
                if (m_Parser.hasOption(m_hAsset))
                {
                    auto A = m_Parser.getOptionArgAs<std::string>(m_hAsset, 0);
                    if (std::holds_alternative<xerr>(A)) return "TextureResidency: bad -Asset";
                    xtexture_residency::Request(xresource::g_Mgr, xresource_editor::commands::ParseAssetGuid(std::get<std::string>(A)), Top);
                }
                else xtexture_residency::RequestAll(xresource::g_Mgr, Top);
            }
            const auto S = xtexture_residency::getStats(xresource::g_Mgr);
            const auto V = xresource::g_Mgr.getUserData<resource_mgr_user_data>().m_Device.getMemoryStats();      // (xGPU's device memory: its 64 MB blocks, the ranges in them, what is free inside)
            return std::format("TextureResidency: textures {}, moving {}, pending {}, queued jobs {}, loaded in place {}, big mips {:.1f} MB, in flight {:.1f} MB, budget {} | VRAM blocks {} ({} ranges, {:.1f} MB free in them), {} of their own"
                              , S.m_nTextures, S.m_nMoving, S.m_nPending, S.m_nWaitingJobs, S.m_nInPlace, S.m_Bytes / 1048576.0, S.m_Reserved / 1048576.0
                              , S.m_Budget ? std::format("{} MB", S.m_Budget >> 20) : std::string("none")
                              , V.m_nBlocks, V.m_nRanges, V.m_FreeBytes / 1048576.0, V.m_nDedicated);
        }
        xcmdline::parser::handle m_hTop, m_hAsset, m_hBudget;
    };

    // GeomResidency: scripted residency requests to the editor's static geometries (xgeom_static_residency, as TextureResidency): the finest
    // LOD their GPU buffers hold. Immediate: the data stays in RAM (the GI reads it)
    struct geom_residency_cmd : xlevel::commands::level_query_command
    {
        geom_residency_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "GeomResidency", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Which LODs the loaded static geometries keep on the GPU: -FinestLOD n (0: all of them), for every geometry or the one of -Asset. Without arguments: the state. Usage: GeomResidency [-FinestLOD n] [-Asset guid]"; }
        void RegisterArguments() noexcept override
        {
            m_hLOD   = m_Parser.addOption("FinestLOD", "The finest LOD kept (0: all)", false, 1);
            m_hAsset = m_Parser.addOption("Asset", "One geometry's resource guid (32 hex digits); none: all", false, 1);
        }
        std::string Query() noexcept override
        {
            if (m_Parser.hasOption(m_hLOD))
            {
                auto L = m_Parser.getOptionArgAs<std::string>(m_hLOD, 0);
                if (std::holds_alternative<xerr>(L)) return "GeomResidency: bad -FinestLOD";
                const int Finest = std::atoi(std::get<std::string>(L).c_str());
                if (m_Parser.hasOption(m_hAsset))
                {
                    auto A = m_Parser.getOptionArgAs<std::string>(m_hAsset, 0);
                    if (std::holds_alternative<xerr>(A)) return "GeomResidency: bad -Asset";
                    xgeom_static_residency::Request(xresource::g_Mgr, xresource_editor::commands::ParseAssetGuid(std::get<std::string>(A)), Finest);
                }
                else xgeom_static_residency::RequestAll(xresource::g_Mgr, Finest);
            }
            const auto S = xgeom_static_residency::getStats(xresource::g_Mgr);
            return std::format("GeomResidency: geometries {}, reduced {}, on the GPU {:.1f} MB of {:.1f} MB", S.m_nGeoms, S.m_nReduced, S.m_Bytes / 1048576.0, S.m_FullBytes / 1048576.0);
        }
        xcmdline::parser::handle m_hLOD, m_hAsset;
    };

    // CloseResourceEditor: the editor menu's Close. Without -Save it closes the editor and drops what was not saved (what a script wants); with -Save it does what a person is offered:
    //   -Save true     saves the changes, then closes (an editor that cannot save stays open and says why)
    //   -Save false    closes and drops them
    //   -Save ask      what the menu's Close does: closes at once when nothing is pending, otherwise opens the question (Save / Don't Save / Cancel) and leaves the editor open
    //   -Save cancel   answers that question with Cancel
    struct close_resource_editor_cmd : xlevel::commands::level_query_command
    {
        close_resource_editor_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "CloseResourceEditor", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Closes the editor of a resource, like the editor menu's Close. Without -Save the changes that are not saved are dropped; -Save true saves them first, false drops them, ask opens the question a person is asked, cancel answers it with Cancel. Usage: CloseResourceEditor -Asset assetguid [-Save true|false|ask|cancel]"; }
        void RegisterArguments() noexcept override
        {
            m_hAsset = m_Parser.addOption("Asset", "Resource guid, 32 hex digits", true, 1);
            m_hSave  = m_Parser.addOption("Save", "true: save first, false: drop the changes, ask: ask as the menu does, cancel: answer the question with Cancel", false, 1);
        }
        std::string Query() noexcept override
        {
            auto AssetArg = m_Parser.getOptionArgAs<std::string>(m_hAsset, 0);
            if (std::holds_alternative<xerr>(AssetArg)) return "CloseResourceEditor: bad arguments";
            auto* pEditors = FindResourceEditors();
            auto* pEditor  = pEditors ? pEditors->Find(xresource_editor::commands::ParseAssetGuid(std::get<std::string>(AssetArg))) : nullptr;
            if (!pEditor) return "CloseResourceEditor: no open editor for that resource";

            std::string Save;
            if (auto SaveArg = m_Parser.getOptionArgAs<std::string>(m_hSave, 0); !std::holds_alternative<xerr>(SaveArg)) Save = std::get<std::string>(SaveArg);

            if (Save.empty() || Save == "false") { pEditor->m_bAskClose = false; pEditor->m_bOpen = false; return ""; }      // the host drops it at the start of the next frame
            if (Save == "true")
            {
                if (pEditor->HasPendingChanges()) pEditor->SaveChanges();
                if (pEditor->HasPendingChanges()) return "CloseResourceEditor: the changes could not be saved: the editor stays open";
                pEditor->m_bAskClose = false; pEditor->m_bOpen = false;
                return "";
            }
            if (Save == "ask")
            {
                if (!pEditor->HasPendingChanges()) { pEditor->m_bOpen = false; return ""; }
                if (pEditor->m_bAskClose) return "CloseResourceEditor: the question is already open";
                pEditor->RequestClose();
                return std::format("CloseResourceEditor: asking whether to save the changes of {}", pEditor->DisplayName());
            }
            if (Save == "cancel")
            {
                const bool bAsking = pEditor->m_bAskClose;
                pEditor->m_bAskClose = false;
                return bAsking ? "CloseResourceEditor: cancelled: the editor stays open" : "CloseResourceEditor: there was no question to cancel";
            }
            return "CloseResourceEditor: -Save is true, false, ask or cancel";
        }
        xcmdline::parser::handle m_hAsset, m_hSave;
    };

    // SaveAll: Save All of the menus and of Ctrl+Shift+S. Fires the editor's Save All event: everything that has unsaved work saves it - the open editors (the Levels among them) and the asset database
    // (the renames and moves of the resource view) - and whatever else subscribed. (The command Save is the local one: the Level's.)
    struct save_all_cmd : xlevel::commands::level_query_command
    {
        save_all_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "SaveAll", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Saves everything in the editor that has unsaved work, whoever owns it: the open editors and the changes of the resource view (renames, moves). Usage: SaveAll"; }
        void RegisterArguments() noexcept override {}
        std::string Query() noexcept override
        {
            const auto Report = xeditor::SaveAllNow();
            if (Report.empty()) return "SaveAll: nothing was pending";
            auto Join = [](const std::vector<std::string>& L) { std::string S; for (const auto& N : L) S += (S.empty() ? "" : ", ") + N; return S; };
            std::string Out = std::format("SaveAll: saved {}: {}", Report.m_Saved.size(), Join(Report.m_Saved));
            if (!Report.m_Failed.empty()) Out += std::format("; failed {}: {}", Report.m_Failed.size(), Join(Report.m_Failed));
            return Out;
        }
    };

    // Unsaved: what has unsaved work, without saving it - what Save All would save, and what the Save buttons of the editors pulse for. For whoever cannot see the button (a command line, an AI that
    // drives the editor).
    struct unsaved_cmd : xlevel::commands::level_query_command
    {
        unsaved_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "Unsaved", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Lists what has unsaved work, without saving it: the open editors with changes that are not saved, and the resource database (renames, moves). What SaveAll would save. Usage: Unsaved"; }
        void RegisterArguments() noexcept override {}
        std::string Query() noexcept override
        {
            std::vector<std::string> Names;
            if (auto* pEditors = FindResourceEditors())
                for (auto& E : pEditors->m_List)
                    if (E && E->m_bOpen && E->isLoaded() && E->HasPendingChanges()) Names.push_back(E->DisplayName());
            if (xresource_editor::g_LibMgr.isReadyToSave()) Names.push_back("Resource database");
            if (Names.empty()) return "Unsaved: nothing";
            std::string Joined;
            for (const auto& N : Names) Joined += (Joined.empty() ? "" : ", ") + N;
            return std::format("Unsaved: {}: {}", Names.size(), Joined);
        }
    };

    // LocateResource: the "find in the resource browser" button of a resource reference. The Resources tab of the drawer shows the resource (its folder is current, what hid it is cleared) and
    // the drawer is open on it.
    struct locate_resource_cmd : xlevel::commands::level_query_command
    {
        locate_resource_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "LocateResource", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Finds a resource in the resource browser of the drawer, as the button of a resource reference does: its folder is shown, the search and the type filter that hid it are cleared, it is selected, and the drawer is open on the Resources tab. Usage: LocateResource -Asset assetguid"; }
        void RegisterArguments() noexcept override { m_hAsset = m_Parser.addOption("Asset", "Resource guid, 32 hex digits", true, 1); }
        std::string Query() noexcept override
        {
            auto AssetArg = m_Parser.getOptionArgAs<std::string>(m_hAsset, 0);
            if (std::holds_alternative<xerr>(AssetArg)) return "LocateResource: bad arguments";
            const auto Guid = xresource_editor::commands::ParseAssetGuid(std::get<std::string>(AssetArg));
            if (Guid.empty()) return "LocateResource: not a resource guid";
            auto& Reference = xresource_editor::g_ReferenceHost;
            if (!Reference.m_Locate || !Reference.m_Locate(Guid)) return "LocateResource: the resource is not in the browser (it is in the trash, or in no open library)";
            return "LocateResource: ok";
        }
        xcmdline::parser::handle m_hAsset;
    };

    // ResourcePath: the whole path of a resource in the resource browser (library, folders, name), what the hint of a resource reference shows.
    struct resource_path_cmd : xlevel::commands::level_query_command
    {
        resource_path_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "ResourcePath", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Says the whole path of a resource in the resource browser (library, folders, name), as the hint of a resource reference shows it. Usage: ResourcePath -Asset assetguid"; }
        void RegisterArguments() noexcept override { m_hAsset = m_Parser.addOption("Asset", "Resource guid, 32 hex digits", true, 1); }
        std::string Query() noexcept override
        {
            auto AssetArg = m_Parser.getOptionArgAs<std::string>(m_hAsset, 0);
            if (std::holds_alternative<xerr>(AssetArg)) return "ResourcePath: bad arguments";
            const auto Guid = xresource_editor::commands::ParseAssetGuid(std::get<std::string>(AssetArg));
            if (Guid.empty()) return "ResourcePath: not a resource guid";
            const auto Path = xresource_editor::ResourceFullPath(Guid);
            return Path.empty() ? "ResourcePath: no open library has that resource" : "ResourcePath: " + Path;
        }
        xcmdline::parser::handle m_hAsset;
    };

    // ListAssetDependents: the resources that point at a source file, the list behind the "Find Resource" and "Open Resource" items of the menu of a file in the Assets tab: the guid (what
    // LocateResource and OpenResourceEditor take) and the full path of each in the resource browser.
    struct list_asset_dependents_cmd : xlevel::commands::level_query_command
    {
        list_asset_dependents_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "ListAssetDependents", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Lists the resources that point at a source file, as the Find Resource / Open Resource items of the menu of the file in the Assets tab do: the guid and the full path of each. Usage: ListAssetDependents -Path Assets/Folder/file.png"; }
        void RegisterArguments() noexcept override { m_hPath = m_Parser.addOption("Path", "The file, relative to its library (Assets/Folder/file.png) or a full path", true, 1); }
        std::string Query() noexcept override
        {
            auto PathArg = m_Parser.getOptionArgAs<std::string>(m_hPath, 0);
            if (std::holds_alternative<xerr>(PathArg)) return "ListAssetDependents: bad arguments";
            xresource_editor::library::guid Library{};
            std::wstring                    LibraryRel;
            auto& Mgr = xresource_editor::g_LibMgr;
            if (!Mgr.ResolveAssetFile(std::filesystem::path(std::get<std::string>(PathArg)).wstring(), Library, LibraryRel)) return "ListAssetDependents: no open library has that file";
            std::size_t Total = 0;
            const auto  Resources = Mgr.GetDependents(Library, LibraryRel, 1000, Total);
            std::string Out = std::format("ListAssetDependents: {}\n", Total);
            for (auto& R : Resources) Out += std::format("{:016X}{:016X}  {}\n", R.m_Guid.m_Instance.m_Value, R.m_Guid.m_Type.m_Value, R.m_Path);
            return Out;
        }
        xcmdline::parser::handle m_hPath;
    };

    // LocateAsset: the "find in the Assets tab" button of an asset reference (the source file of a descriptor). The Assets tab of the drawer shows the file (its folder is current, what hid it is
    // cleared, it is the selection) and the drawer is open on that tab.
    struct locate_asset_cmd : xlevel::commands::level_query_command
    {
        locate_asset_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "LocateAsset", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Finds a source file in the Assets tab of the drawer, as the button of an asset reference does: its folder is shown, the search that hid it is cleared, it is selected, and the drawer is open on the Assets tab. Usage: LocateAsset -Path Assets/Folder/file.png"; }
        void RegisterArguments() noexcept override { m_hPath = m_Parser.addOption("Path", "The file, relative to its library (Assets/Folder/file.png) or a full path", true, 1); }
        std::string Query() noexcept override
        {
            auto PathArg = m_Parser.getOptionArgAs<std::string>(m_hPath, 0);
            if (std::holds_alternative<xerr>(PathArg)) return "LocateAsset: bad arguments";
            auto& Reference = xresource_editor::g_AssetReferenceHost;
            if (!Reference.m_Locate || !Reference.m_Locate(std::filesystem::path(std::get<std::string>(PathArg)).wstring())) return "LocateAsset: no open library has that file";
            return "LocateAsset: ok";
        }
        xcmdline::parser::handle m_hPath;
    };

    // GetBrowserState: where the resource browser is and what the drawer shows. SetBrowserSearch types in its search box.
    struct get_browser_state_cmd : xlevel::commands::level_query_command
    {
        get_browser_state_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "GetBrowserState", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Says where the resource browser is (folder, selection, history, search and type filter) and whether the drawer is open on it. Usage: GetBrowserState"; }
        void RegisterArguments() noexcept override {}
        std::string Query() noexcept override
        {
            auto* pHost    = xeditor::host::current();
            auto* pBrowser = pHost ? pHost->find<xresource_editor::asset_browser>() : nullptr;
            if (!pBrowser) return "GetBrowserState: no browser";
            const auto& Drawer = pHost->drawer_for(xeditor::FocusedDrawerViewport()->ID);
            return std::format("GetBrowserState: ok\nDrawer={}\nDrawerTab={}\n{}", Drawer.m_bOpen ? "open" : "closed", Drawer.m_ActiveTab, pBrowser->DescribeBrowser());
        }
    };

    struct set_browser_search_cmd : xlevel::commands::level_query_command
    {
        set_browser_search_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "SetBrowserSearch", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Types a text into the search box of the resource browser (an empty text clears it). Usage: SetBrowserSearch [-Text name]"; }
        void RegisterArguments() noexcept override { m_hText = m_Parser.addOption("Text", "The text to search for", false, 1); }
        std::string Query() noexcept override
        {
            auto* pHost    = xeditor::host::current();
            auto* pBrowser = pHost ? pHost->find<xresource_editor::asset_browser>() : nullptr;
            if (!pBrowser) return "SetBrowserSearch: no browser";
            auto TextArg = m_Parser.getOptionArgAs<std::string>(m_hText, 0);
            pBrowser->m_SearchString = std::holds_alternative<xerr>(TextArg) ? std::string() : std::get<std::string>(TextArg);
            return "SetBrowserSearch: ok";
        }
        xcmdline::parser::handle m_hText;
    };

    // The guid-addressed way to reach an open editor's own commands (the friendlier way is Name\Command from `list`).
    struct resource_editor_command_cmd : xlevel::commands::level_query_command
    {
        resource_editor_command_cmd(xundo::system& System, void* pDataBase) noexcept : xlevel::commands::level_query_command(System, "ResourceEditorCommand", pDataBase) { RegisterArguments(); }
        const char* getCommandHelp() const noexcept override { return "Runs a command of an open resource editor, addressed by resource guid. Usage: ResourceEditorCommand -Asset assetguid -Cmd \"SetProperty ...\""; }
        void RegisterArguments() noexcept override
        {
            m_hAsset = m_Parser.addOption("Asset", "Resource guid, 32 hex digits", true, 1);
            m_hCmd   = m_Parser.addOption("Cmd",   "Inner command string",  true, 1);
        }
        std::string Query() noexcept override
        {
            auto AssetArg = m_Parser.getOptionArgAs<std::string>(m_hAsset, 0);
            auto CmdArg   = m_Parser.getOptionArgAs<std::string>(m_hCmd, 0);
            if (std::holds_alternative<xerr>(AssetArg) || std::holds_alternative<xerr>(CmdArg))
                return "ResourceEditorCommand: bad arguments";

            auto* pEditors = FindResourceEditors();
            auto* pEditor  = pEditors ? pEditors->Find(xresource_editor::commands::ParseAssetGuid(std::get<std::string>(AssetArg))) : nullptr;
            if (!pEditor) return "ResourceEditorCommand: no open editor for that resource";
            return xeditor::host::current()->run_on(pEditor->getUndo(), std::get<std::string>(CmdArg));
        }
        xcmdline::parser::handle m_hAsset, m_hCmd;
    };
}

#endif // LevelEditor_COMMANDS_RESOURCE_EDITORS_H
