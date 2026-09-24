#ifndef XEDITOR_THUMBNAIL_CAMERA_FIT_H
#define XEDITOR_THUMBNAIL_CAMERA_FIT_H
#pragma once

// Shared by every mesh-shaped thumbnail renderer (GeomStatic, GeomSkin, ...): the exact camera
// distance that makes a real AABB's silhouette fill a FIXED viewing angle's frame edge-to-edge.
//
// Every interactive preview's own auto-fit (the "S.m_Distance == -1" branch each editor's Draw()
// has) uses the angle-agnostic bound instead: half_extent*sqrt(3) / sin(halfFov), sized off the
// bounding SPHERE. That bound has to stay correct for ANY orbit angle the user might pick next, so
// it is deliberately conservative - a mesh's real silhouette from one fixed corner-on angle is
// smaller than its circumscribing sphere, which left visible empty margin in a 128x128 thumbnail
// (first worked out, and confirmed live, for a synthetic cube in xtexture_thumbnail.h's DrawCube).
//
// Since a thumbnail's viewing angle is FIXED (never orbited), the exact tightest-fit distance for
// THAT angle can be solved directly instead: project the AABB's 8 corners through a reference-
// distance view at the real Angles/Fov/Aspect, find how far the worst corner lands outside the
// [-1,1] NDC frame, then scale distance by exactly that factor. Perspective NDC extent scales as
// ~1/Distance once Distance is much larger than the object, so one scale-and-done pass is enough -
// no iteration needed (DrawCube's own comment checks an 8x-radius reference distance keeps this
// under a pixel of error at 128x128; the 100x used here is even safer).
#include "source/Tools/xgpu_view.h"

#include <algorithm>
#include <cmath>

namespace xeditor
{
    // View must already have Fov/Aspect/Viewport set. Calls View.LookAt(...) as a side effect (the
    // caller still needs its own final LookAt(Distance, Angles, Center) before drawing - this only
    // solves for Distance). Min/Max are the object's AABB corners, in the same space the real draw
    // will render it in (world space, when the mesh sits at the origin the way every thumbnail here
    // draws it - see each renderer's own comment).
    inline float ComputeTightFitDistance(xgpu::tools::view& View, const xmath::radian3& Angles, const xmath::fvec3& Center, const xmath::fvec3& Min, const xmath::fvec3& Max) noexcept
    {
        const xmath::fvec3 Half        = (Max - Min) * 0.5f;
        const float        Radius      = Half.Length();
        const float        RefDistance = std::max(100.0f * Radius, 0.01f);

        View.LookAt(RefDistance, Angles, Center);
        const auto& RefW2C = View.getW2C();

        float MaxNdc = 0.0f;
        for (float sx : { -1.0f, 1.0f }) for (float sy : { -1.0f, 1.0f }) for (float sz : { -1.0f, 1.0f })
        {
            const xmath::fvec3 Corner{ Center.m_X + sx * Half.m_X, Center.m_Y + sy * Half.m_Y, Center.m_Z + sz * Half.m_Z };
            const auto Clip = RefW2C * xmath::fvec4{ Corner.m_X, Corner.m_Y, Corner.m_Z, 1.0f };
            MaxNdc = std::max({ MaxNdc, std::fabs(Clip.m_X / Clip.m_W), std::fabs(Clip.m_Y / Clip.m_W) });
        }
        return RefDistance * std::max(MaxNdc, 1e-6f);
    }
}

#endif // XEDITOR_THUMBNAIL_CAMERA_FIT_H
