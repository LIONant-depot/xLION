#ifndef XEDITOR_THUMBNAIL_CACHE_H
#define XEDITOR_THUMBNAIL_CACHE_H
#pragma once

// The disk cache + runtime atlas half of the resource-thumbnail system (see xeditor_thumbnail.h for the
// "ask the editor to draw itself" half). A pure UI/view concern, not a document one - an editor stays usable
// headless; nothing here is reached unless something (the resource browser) actually asks for a thumbnail.
//
// A resource never requested here (never scrolled into view) never has anything computed or written for it.
//
// This half owns NO GPU render target or render pass of its own - every thumbnail_renderer owns whatever
// offscreen target(s) it needs internally (see xeditor_thumbnail.h's own comment) and hands back a
// finished xbitmap; this cache's only jobs are asking a type's renderer to (keep) render(ing) a guid,
// and SERIALIZING the result once it has one: writing it to the on-disk PNG cache
// (xbmp::tools::writers::SaveSTDImage, the same real-PNG-via-stb_image_write path already used
// elsewhere in this codebase for exactly this) and uploading it into the runtime atlas cell texture the
// browser actually draws with.
#include "source/Tools/Editor/xeditor_thumbnail.h"
#include "source/Tools/Editor/xeditor_resource_editor.h"
#include "source/xGPU.h"
#include "dependencies/xbmp_tools/src/xbmp_tools.h"
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_asset_mgr.h"

#include <filesystem>
#include <future>
#include <list>
#include <unordered_map>
#include <unordered_set>

namespace xeditor
{
    // One resource's 32x32-grid cell inside the shared atlas texture, in pixels.
    struct thumbnail_cache
    {
        static constexpr int s_CellPixels = 128;
        static constexpr int s_Cols       = 8;
        static constexpr int s_Rows       = 8;
        static constexpr int s_MaxCells   = s_Cols * s_Rows;   // 64 - grown to a second page only if this genuinely isn't enough

        // The sharded on-disk cache path for one resource, mirroring Descriptors' own
        // <lowbyte>/<2ndbyte>/<hex>  scheme (xresource_editor_asset_mgr.h's NewAsset) - both instance and type in the
        // filename since, unlike Descriptors, there is no per-type directory here to disambiguate a
        // (astronomically unlikely, but not architecturally prevented) instance-only collision.
        static std::wstring DiskPath(xresource::full_guid Guid) noexcept
        {
            const auto LibGuid = open_resource_editors::FindLibraryOf(Guid);
            std::wstring Root;
            xresource_editor::g_LibMgr.m_mLibraryDB.FindAsReadOnly(LibGuid, [&](const std::unique_ptr<xresource_editor::library_db>& Lib) { Root = Lib->m_Library.m_Path; });
            if (Root.empty()) return {};

            const std::uint64_t V = Guid.m_Instance.m_Value;
            return std::format(L"{}/Cache/Thumbnails/{:02X}/{:02X}/{:016X}{:016X}.png"
                , Root, V & 0xff, (V >> 8) & 0xff, V, Guid.m_Type.m_Value);
        }

        // The main entry point: called once per visible row per frame by the browser (through a hook, not a
        // direct include - see xresource_editor_asset_browser.h's m_OnRequestThumbnail). Returns an invalid ref (the
        // browser then falls back to the type icon) until a real thumbnail is actually ready. Returns
        // xresource_editor::plugin_icon_ref directly (texture handle + UV rect) rather than a same-shaped type of its
        // own - it's exactly what the browser's existing type-icon atlas already returns and draws with.
        xresource_editor::plugin_icon_ref RequestThumbnail(xgpu::device& Device, xresource::full_guid Guid) noexcept
        {
            if (!ThumbnailRendererFactories().contains(Guid.m_Type)) return {};   // this type never opted in

            EnsureAtlas(Device);

            if (auto It = m_Cells.find(Guid); It != m_Cells.end())
            {
                m_Order.remove(Guid);
                m_Order.push_front(Guid);
                return CellRef(It->second);
            }

            if (m_InFlight.contains(Guid)) { PollInFlight(Device); return {}; }

            // Not resident, not already being worked on - kick a background disk-cache check. The common
            // case (already generated on a previous run) never touches the GPU at all past this.
            const std::wstring Path = DiskPath(Guid);
            if (Path.empty()) return {};

            // A thumbnail older than the compiled resource shows an older version of it (the compile finished while the editor was not looking: at startup by the
            // compiler-newer rule, from outside the session, ...): it counts as missing, so a fresh one is drawn and written over it.
            std::filesystem::file_time_type ResourceTime = std::filesystem::file_time_type::min();
            xresource_editor::g_LibMgr.getNodeInfo(Guid, [&](const xresource_editor::library_db::info_node& Node) { if (Node.m_bHasResource) ResourceTime = Node.m_ResourceTime; });

            m_InFlight.emplace(Guid, in_flight{ .m_DiskLoad = std::async(std::launch::async, [Path, ResourceTime]() noexcept -> xbitmap
                {
                    std::error_code Ec;
                    const auto ThumbnailTime = std::filesystem::last_write_time(Path, Ec);
                    if (!Ec && ThumbnailTime < ResourceTime) return {};

                    xbitmap Bmp;
                    if (auto Err = xbmp::tools::loader::LoadSTDImage(Bmp, Path); Err) return {};
                    return Bmp;
                })
            });
            PollInFlight(Device);
            return {};
        }

        // Drops a resource's cached thumbnail (disk + the atlas cell, if it holds one) so the next request
        // regenerates fresh. Wired to xresource_editor::g_LibMgr.m_OnCompilationState in Init() below.
        void Invalidate(xresource::full_guid Guid) noexcept
        {
            std::error_code Ec;
            const std::wstring Path = DiskPath(Guid);
            if (!Path.empty()) std::filesystem::remove(Path, Ec);

            if (auto It = m_Cells.find(Guid); It != m_Cells.end())
            {
                m_FreeCells.push_back(It->second);
                m_Order.remove(Guid);
                m_Cells.erase(It);
            }
            m_InFlight.erase(Guid);
        }

        // Registers the compile-completion hook once and remembers which window to hand each renderer for
        // recording its own offscreen render - call from wherever the app already sets up its long-lived
        // singletons (this object itself needs to outlive both the registration and the window). Without a
        // window (e.g. a headless CLI host), disk-cache hits still work fine; a genuine generation just
        // never resolves, since there is nothing to render with - the same "no GPU, no preview" degradation
        // every resource_editor already has (xeditor::open_resource_editors::m_pDevice's own comment).
        void Init(xgpu::window& Window) noexcept
        {
            m_pWindow = &Window;
            if (m_bCompileHookRegistered) return;
            m_bCompileHookRegistered = true;
            xresource_editor::g_LibMgr.m_OnCompilationState.Register<&thumbnail_cache::OnCompilationState>(*this);
        }

        ~thumbnail_cache() noexcept
        {
            if (m_bCompileHookRegistered) xresource_editor::g_LibMgr.m_OnCompilationState.RemoveDelegates(this);
        }

    private:
        struct in_flight
        {
            std::future<xbitmap>       m_DiskLoad;                  // valid while checking disk
            bool                       m_bDiskMissed    = false;    // m_DiskLoad already .get() once and came up empty - a future can only be consumed once, never touch m_DiskLoad again after this flips true
            bool                       m_bStarted       = false;    // disk missed - already made at least one Render() call (counts once against the generation budget, further polls are free)
        };

        xresource_editor::plugin_icon_ref CellRef(int Cell) noexcept
        {
            const int cx = Cell % s_Cols, cy = Cell / s_Cols;
            const float U = 1.0f / s_Cols, V = 1.0f / s_Rows;
            // plugin_icon_ref::m_pTexture must be a pointer to the PUBLIC xgpu::texture wrapper (matching
            // xresource_editor_asset_browser.h's own m_IconAtlasGPUHandle convention: "shared_ptr<xgpu::texture> ->
            // shared_ptr<void>", cast back with static_cast<xgpu::texture*> at the drawing side) - NOT
            // m_Private.get() (one level too deep, the internal Vulkan backend object). Passing the wrong
            // level here was a real, confirmed bug: the browser's ImageWithBg call reinterpreted whatever
            // bytes happen to sit at vulkan::texture's own layout as if they were xgpu::texture's
            // shared_ptr, producing a garbage-but-build-consistent VkImageView and crashing the app.
            return { &m_AtlasTexture, cx * U, cy * V, (cx + 1) * U, (cy + 1) * V };
        }

        static bool Ok(xgpu::device::error* pErr) noexcept
        {
            if (!pErr) return true;
            std::printf("Thumbnail cache: %s\n", std::string(xgpu::getErrorMsg(pErr)).c_str());
            return false;
        }

        void EnsureAtlas(xgpu::device& Device) noexcept
        {
            if (m_AtlasTexture.m_Private) return;
            // sRGB (m_isGamma - default true, matching the existing plugin-icon atlas, which never overrides
            // it): this atlas is sampled straight for on-screen display, same as that one, not read back into
            // a shader computation - a UNORM/linear atlas would show visibly washed-out colors next to the
            // type-icon atlas it sits beside in the same browser row.
            (void)Ok(Device.Create(m_AtlasTexture, { .m_Format = xgpu::texture::format::R8G8B8A8_UNORM
                , .m_Width = s_Cols * s_CellPixels, .m_Height = s_Rows * s_CellPixels, .m_isGamma = true }));
            for (int i = s_MaxCells - 1; i >= 0; --i) m_FreeCells.push_back(i);
        }

        // Claims a cell for Guid, evicting the least-recently-used one if the atlas is full.
        int ClaimCell(xresource::full_guid Guid) noexcept
        {
            if (!m_FreeCells.empty())
            {
                const int Cell = m_FreeCells.back();
                m_FreeCells.pop_back();
                return Cell;
            }
            // Evict the least recently used resident (the back of m_Order that still owns a cell).
            for (auto It = m_Order.rbegin(); It != m_Order.rend(); ++It)
            {
                if (auto Found = m_Cells.find(*It); Found != m_Cells.end())
                {
                    const int Cell = Found->second;
                    m_Cells.erase(Found);
                    m_Order.erase(std::next(It).base());
                    return Cell;
                }
            }
            return 0;   // unreachable once the atlas has ever been populated - s_MaxCells is never 0
        }

        void InsertBitmap(xgpu::device& Device, xresource::full_guid Guid, const xbitmap& Bmp) noexcept
        {
            if (Bmp.getWidth() != s_CellPixels || Bmp.getHeight() != s_CellPixels || Bmp.getFormat() != xbitmap::format::R8G8B8A8) return;
            const int Cell = ClaimCell(Guid);
            const int cx = (Cell % s_Cols) * s_CellPixels, cy = (Cell / s_Cols) * s_CellPixels;
            auto Pixels = Bmp.getMip<xcolori>(0);   // std::span<const xcolori> already - Bmp is const
            (void)Ok(Device.UpdateTexture(m_AtlasTexture, cx, cy, s_CellPixels, s_CellPixels, std::as_bytes(Pixels)));
            m_Cells[Guid] = Cell;
            m_Order.push_front(Guid);
        }

        // The type's persistent renderer, created and Init()'d once on first use.
        thumbnail_renderer* RendererFor(xgpu::device& Device, xresource::type_guid Type) noexcept
        {
            auto RendererIt = ThumbnailRendererFactories().find(Type);
            if (RendererIt == ThumbnailRendererFactories().end()) return nullptr;

            auto& pRenderer = m_Renderers[Type];
            if (!pRenderer) pRenderer = RendererIt->second();
            if (!pRenderer->Init(Device)) return nullptr;
            return pRenderer.get();
        }

        // Advances every in-flight GUID by one step: picks up a finished disk-load (no GPU work at all), or
        // - for a confirmed disk miss - polls the type's own renderer (see xeditor_thumbnail.h: it owns its
        // own render target/readback entirely now, this just keeps asking until it hands back a bitmap).
        // Starting a NEW render (this guid's first poll) is rate-limited so a big scroll can't stall a
        // frame; a guid already mid-render is cheap to re-poll (its renderer just checks a flag) and never
        // counts against the budget.
        void PollInFlight(xgpu::device& Device) noexcept
        {
            int StartBudget = 2;   // new renders STARTED this call; re-polling an already-started one is free
            for (auto It = m_InFlight.begin(); It != m_InFlight.end(); )
            {
                auto& [Guid, Flight] = *It;

                if (!Flight.m_bDiskMissed)
                {
                    // A std::future can only ever be waited on / consumed once - m_bDiskMissed remembers a
                    // miss found on an EARLIER pass (e.g. the generation budget was exhausted that time) so
                    // this branch is never re-entered for the same entry; re-touching m_DiskLoad after its
                    // one and only get() is undefined behaviour - confirmed live: a reproducible crash, with
                    // or without validation layers, on exactly this second touch.
                    if (Flight.m_DiskLoad.wait_for(std::chrono::seconds(0)) != std::future_status::ready) { ++It; continue; }
                    xbitmap Bmp = Flight.m_DiskLoad.get();
                    if (Bmp.getWidth() != 0) { InsertBitmap(Device, Guid, Bmp); It = m_InFlight.erase(It); continue; }
                    Flight.m_bDiskMissed = true;
                }

                // Disk missed - needs a real render.
                if (!Flight.m_bStarted)
                {
                    if (StartBudget <= 0) { ++It; continue; }
                    --StartBudget;
                    Flight.m_bStarted = true;
                }

                if (!m_pWindow) { It = m_InFlight.erase(It); continue; }   // headless host - see Init()'s own comment

                auto* pRenderer = RendererFor(Device, Guid.m_Type);
                if (!pRenderer) { It = m_InFlight.erase(It); continue; }   // unregistered type or Init failure

                xbitmap Bmp;
                if (!pRenderer->Render(Device, *m_pWindow, Guid, Bmp)) { ++It; continue; }   // not ready yet - poll again next tick

                InsertBitmap(Device, Guid, Bmp);

                // The disk write doesn't need the GPU at all - background it.
                const std::wstring Path = DiskPath(Guid);
                if (!Path.empty())
                {
                    std::async(std::launch::async, [Path, Bmp = std::move(Bmp)]() noexcept
                    {
                        std::error_code Ec;
                        if (auto Parent = std::filesystem::path(Path).parent_path(); !Parent.empty()) std::filesystem::create_directories(Parent, Ec);
                        (void)xbmp::tools::writers::SaveSTDImage(Path, Bmp);
                    }).wait();   // TODO: track this future instead of blocking - acceptable for now, disk write of one small PNG
                }
                It = m_InFlight.erase(It);
            }
        }

        void OnCompilationState(xresource_editor::library_mgr&, xresource_editor::library::guid, xresource::full_guid Guid, std::shared_ptr<xresource_editor::compilation::historical_entry::log>& Log) noexcept
        {
            if (!Log) return;
            xcontainer::lock::scope Lock(*Log);
            using result = xresource_editor::compilation::historical_entry::result;
            const auto R = Log->get().m_Result;
            if (R == result::SUCCESS || R == result::SUCCESS_WARNINGS) Invalidate(Guid);
        }

        xgpu::window*                                                            m_pWindow = nullptr;
        xgpu::texture                                                            m_AtlasTexture;
        std::unordered_map<xresource::full_guid, int>                            m_Cells;         // guid -> cell index
        std::list<xresource::full_guid>                                          m_Order;         // most-recently-used first
        std::vector<int>                                                         m_FreeCells;
        std::unordered_map<xresource::full_guid, in_flight>                      m_InFlight;
        std::unordered_map<xresource::type_guid, std::unique_ptr<thumbnail_renderer>> m_Renderers; // one persistent renderer per type
        bool                                                                      m_bCompileHookRegistered = false;
    };

    inline thumbnail_cache g_ThumbnailCache;
}

#endif // XEDITOR_THUMBNAIL_CACHE_H
