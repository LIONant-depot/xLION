#ifndef XEDITOR_THUMBNAIL_H
#define XEDITOR_THUMBNAIL_H
#pragma once

// The "ask the editor to draw itself" half of the resource-thumbnail system: a resource type registers a
// small, persistent (constructed once, reused for every resource of that type) renderer that owns its
// own offscreen render target(s), draws one resource into them however it needs to, and hands back a
// finished, CPU-side bitmap. This is deliberately the same shape a future read-only viewer's own per-type
// renderer would have (mesh_preview::Draw(CmdBuffer,W,H) already has this shape for material/geom preview
// panels), so a type that grows real viewer support shares this instead of duplicating it. See
// xeditor_thumbnail_cache.h for what actually calls into this (the disk cache, the runtime atlas, the
// generation pipeline) - this header only knows how to reach a type's own renderer, nothing about caching
// or serialization; it never sees a render target or a render pass itself.
//
// A resource type opts in next to its existing auto_register_resource_editor:
//   inline const xeditor::auto_register_thumbnail_renderer g_ThumbReg{ type_guid_v, []{ return std::make_unique<my_thumbnail_renderer>(); } };
// A type with no registration simply never gets asked - the browser keeps showing its type icon.
#include "dependencies/xresource_guid/source/xresource_guid.h"
#include "dependencies/xbitmap/source/xbitmap.h"

#include <functional>
#include <memory>
#include <unordered_map>

namespace xgpu { struct device; struct window; }

namespace xeditor
{
    // One resource type's thumbnail renderer. Owns whatever offscreen colour (and, if it needs real
    // depth testing, depth) target(s) it renders into internally - a renderer that reuses an existing
    // interactive-preview runtime (the GeomStatic/GeomSkin pattern: drive the SAME lit-mesh runtime the
    // panel uses, just headless with a fixed camera) typically owns exactly one small render pass built
    // once in Init() and reused every call.
    //
    // Render is polled once per tick (see xeditor_thumbnail_cache.h::PollInFlight) until it returns true
    // with OutBitmap filled in (128x128, xbitmap::format::R8G8B8A8) - a GPU render recorded this call is
    // only actually complete several engine frames later (xgpu::window::ReadbackTexture's own comment),
    // so most renderers need more than one call to get there: the first call starts the render and
    // returns false, later calls just check whether the deferred readback has completed yet. A renderer
    // only works on one resource at a time (a single reused render target, not one per in-flight guid) -
    // Render for a DIFFERENT guid while still busy with an earlier one simply returns false without
    // starting new work; the cache retries it on a later tick once the renderer frees up.
    struct thumbnail_renderer
    {
        virtual              ~thumbnail_renderer( void )                                                                             noexcept = default;
        virtual bool          Init             ( xgpu::device& Device )                                                              noexcept = 0;
        virtual bool          Render           ( xgpu::device& Device, xgpu::window& Window, xresource::full_guid Guid, xbitmap& OutBitmap ) noexcept = 0;
    };

    using thumbnail_renderer_factory = std::function<std::unique_ptr<thumbnail_renderer>()>;

    inline std::unordered_map<xresource::type_guid, thumbnail_renderer_factory>& ThumbnailRendererFactories() noexcept
    {
        static std::unordered_map<xresource::type_guid, thumbnail_renderer_factory> s_Map;
        return s_Map;
    }

    // A resource type's editor header declares one of these at namespace scope, next to its
    // auto_register_resource_editor: `inline const xeditor::auto_register_thumbnail_renderer g_ThumbReg{ type, factory };`
    struct auto_register_thumbnail_renderer
    {
        auto_register_thumbnail_renderer(xresource::type_guid Type, thumbnail_renderer_factory Factory) noexcept
        {
            ThumbnailRendererFactories()[Type] = std::move(Factory);
        }
    };
}

#endif // XEDITOR_THUMBNAIL_H
