#ifndef XEDITOR_GEOM_FACTS_H
#define XEDITOR_GEOM_FACTS_H
#pragma once

// The read-only facts of a compiled geometry that every geometry editor shows (Static Geom, Skin Geom): how numbers and lengths are written, and the
// meshes -> LODs -> submeshes -> clusters tree with its counts, filled from any compiled geometry that has the same layout (xgeom_static::geom,
// xgeom_skin::geom). Each editor puts these in its own inspector with what only its geometry has (the static GI, the skin's bones).
#include "dependencies/xproperty/source/xcore/my_properties.h"
#include "dependencies/xmath/source/bridge/xmath_to_xproperty.h"
#include "dependencies/xresource_mgr/source/xresource_mgr.h"
#include "plugins/xmaterial_instance.plugin/source/xmaterial_instance_xgpu_rsc_loader.h"

#include <algorithm>
#include <cmath>
#include <span>
#include <sstream>
#include <string>
#include <vector>

namespace xeditor::geom_facts
{
    //---------------------------------------------------------------------------------------------
    // Number formatting
    //---------------------------------------------------------------------------------------------
    inline std::string AddCommas(const std::string& S) noexcept
    {
        std::string Sign, Int, Frac;
        size_t Pos = 0;
        if (!S.empty() && (S[0] == '-' || S[0] == '+')) { Sign = S.substr(0, 1); Pos = 1; }

        const size_t Dot = S.find('.', Pos);
        if (Dot == std::string::npos) Int = S.substr(Pos);
        else { Int = S.substr(Pos, Dot - Pos); Frac = S.substr(Dot); }

        std::string Out;
        int Count = 0;
        for (int i = static_cast<int>(Int.size()) - 1; i >= 0; --i)
        {
            Out.push_back(Int[i]);
            if (++Count == 3 && i > 0) { Out.push_back(','); Count = 0; }
        }
        std::reverse(Out.begin(), Out.end());
        return Sign + Out + Frac;
    }

    // At most MaxDecimals decimals, trailing zeros trimmed, thousands separated.
    inline std::string FormatNumber(double Value, int MaxDecimals) noexcept
    {
        const double Scale   = std::pow(10.0, static_cast<double>(MaxDecimals));
        const double Rounded = MaxDecimals <= 0 ? std::round(Value) : std::round(Value * Scale) / Scale;

        std::ostringstream Stream;
        Stream.setf(std::ios::fixed);
        Stream.precision(MaxDecimals);
        Stream << Rounded;
        std::string S = Stream.str();

        if (S.find('.') != std::string::npos)
        {
            while (!S.empty() && S.back() == '0') S.pop_back();
            if (!S.empty() && S.back() == '.') S.pop_back();
        }
        return AddCommas(S);
    }

    // A length in meters as the most natural of mm, cm, m, Km.
    inline std::string FormatDistance(float Meters) noexcept
    {
        if (std::isnan(Meters)) return "NaN m";
        if (std::isinf(Meters)) return Meters > 0 ? "INF m" : "-INF m";

        const double V = Meters, Abs = std::fabs(V);
        if (Abs >= 1000.0) return FormatNumber(V / 1000.0, 3) + " Km";
        if (Abs >= 1.0)    return FormatNumber(V,           3) + " m";
        if (Abs >= 0.01)   return FormatNumber(V * 100.0,   3) + " cm";
        return                    FormatNumber(V * 1000.0,  3) + " mm";
    }

    //---------------------------------------------------------------------------------------------
    // The tree
    //---------------------------------------------------------------------------------------------
    struct cluster
    {
        int                         m_nVertices;
        int                         m_nFaces;
        xmath::fbbox                m_BBox;

        XPROPERTY_DEF
        ( "Cluster", cluster
        , obj_member<"nVertices", &cluster::m_nVertices, member_help<"Number of vertices in this cluster">>
        , obj_member<"nFaces",    &cluster::m_nFaces, member_help<"Number of faces (triangles) in this cluster">>
        , obj_member<"BBox",      &cluster::m_BBox, member_help<"Axis-aligned bounding box containing this cluster">>
        )
    };

    struct submesh
    {
        int                         m_nVertices;
        int                         m_nFaces;
        xrsc::material_instance_ref m_Material;
        std::vector<cluster>        m_Cluster;

        XPROPERTY_DEF
        ( "Submesh", submesh
        , obj_member<"nVertices", &submesh::m_nVertices, member_help<"Number of vertices in this submesh">>
        , obj_member<"nFaces",    &submesh::m_nFaces, member_help<"Number of faces (triangles) in this submesh">>
        , obj_member<"Material",  &submesh::m_Material, member_help<"Material instance applied to this submesh">>
        , obj_member<"Cluster",   &submesh::m_Cluster, member_help<"List of clusters that make up this submesh">>
        )
    };

    struct lod
    {
        int                         m_nClusters;
        int                         m_nVertices;
        int                         m_nFaces;
        float                       m_ScreenArea;
        std::vector<submesh>        m_Submesh;

        XPROPERTY_DEF
        ( "lod", lod
        , obj_member<"nClusters",   &lod::m_nClusters, member_help<"Number of clusters in this LOD level">>
        , obj_member<"nVertices",   &lod::m_nVertices, member_help<"Number of vertices in this LOD level">>
        , obj_member<"nFaces",      &lod::m_nFaces, member_help<"Number of faces (triangles) in this LOD level">>
        , obj_member<"ScreenArea",  &lod::m_ScreenArea, member_help<"Screen area coverage for this LOD (used for LOD switching)">>
        , obj_member<"Submesh",     &lod::m_Submesh, member_help<"List of submeshes at this LOD level">>
        )
    };

    struct mesh
    {
        std::string                 m_Name;
        int                         m_nClusters;
        int                         m_nVertices;
        int                         m_nFaces;
        int                         m_nMaterials;
        std::vector<lod>            m_LODs;
        xmath::fbbox                m_BBox;

        XPROPERTY_DEF
        ( "mesh", mesh
        , obj_member<"Name",        &mesh::m_Name, member_help<"Name of this mesh">>
        , obj_member<"BBox",        &mesh::m_BBox, member_ui_open<false>, member_help<"Axis-aligned bounding box containing this mesh">>
        , obj_member<"nClusters",   &mesh::m_nClusters, member_help<"Total number of clusters across all LODs">>
        , obj_member<"nVertices",   &mesh::m_nVertices, member_help<"Total number of vertices across all LODs">>
        , obj_member<"nFaces",      &mesh::m_nFaces, member_help<"Total number of faces (triangles) across all LODs">>
        , obj_member<"nMaterials",  &mesh::m_nMaterials, member_help<"Number of different materials used by this mesh">>
        , obj_member<"LODs",        &mesh::m_LODs, member_help<"Level of Detail versions: lower LODs are simpler (fewer polygons) for distant rendering">>
        )
    };

    struct stream_element
    {
        std::string     m_Type;
        std::string     m_Desciption;

        XPROPERTY_DEF
        ( "stream_element", stream_element
        , obj_member<"Type",        &stream_element::m_Type, member_help<"Data type and dimension (e.g., SINT16_3D, UINT16_2D)">>
        , obj_member<"Desciption",  &stream_element::m_Desciption, member_help<"Description of what this element contains and how it's encoded">>
        )
    };

    struct stream
    {
        std::string                 m_Name;
        std::vector<stream_element> m_Elements;

        XPROPERTY_DEF
        ( "stream", stream
        , obj_member<"Name",        &stream::m_Name, member_help<"Stream name: Position (coordinates) or Extras (UV, normals, tangents)">>
        , obj_member<"Elements",    &stream::m_Elements, member_help<"List of data elements in this vertex stream">>
        )
    };
    XPROPERTY_REG2(prop_cluster,        cluster)
    XPROPERTY_REG2(prop_submesh,        submesh)
    XPROPERTY_REG2(prop_lod,            lod)
    XPROPERTY_REG2(prop_mesh,           mesh)
    XPROPERTY_REG2(prop_stream_element, stream_element)
    XPROPERTY_REG2(prop_stream,         stream)

    // The meshes of a compiled geometry (T_GEOM: xgeom_static::geom or xgeom_skin::geom, which share the mesh / LOD / submesh / cluster layout), with their counts.
    // Size: the largest mesh box, the geometry's own size as the inspector shows it
    template<typename T_GEOM>
    inline void FillMeshes(T_GEOM& Geom, std::vector<mesh>& Meshes, xmath::fvec3& Size) noexcept
    {
        Meshes.resize(Geom.m_nMeshes);
        for (auto& M : Geom.getMeshes())
        {
            auto& Mesh = Meshes[static_cast<int>(&M - Geom.getMeshes().data())];

            Mesh.m_nClusters = 0;
            Mesh.m_nFaces    = 0;
            Mesh.m_nVertices = 0;
            Mesh.m_nMaterials = 0;
            Mesh.m_BBox      = M.m_BBox;
            Mesh.m_Name      = M.m_Name.data();
            Mesh.m_LODs.resize(M.m_nLODs);

            auto LODSpan = Geom.getLODs().subspan(M.m_iLOD, M.m_nLODs);
            for (auto& L : LODSpan)
            {
                auto& LOD = Mesh.m_LODs[static_cast<int>(&L - LODSpan.data())];

                LOD.m_ScreenArea = L.m_ScreenArea;
                LOD.m_nClusters  = 0;
                LOD.m_nFaces     = 0;
                LOD.m_nVertices  = 0;
                LOD.m_Submesh.resize(L.m_nSubmesh);

                auto SubmeshSpan = Geom.getSubmeshes().subspan(L.m_iSubmesh, L.m_nSubmesh);
                for (auto& S : SubmeshSpan)
                {
                    auto& Sub = LOD.m_Submesh[static_cast<int>(&S - SubmeshSpan.data())];

                    Sub.m_nFaces    = 0;
                    Sub.m_nVertices = 0;
                    Sub.m_Material.m_Instance = xresource::g_Mgr.getFullGuid(Geom.getDefaultMaterialInstances().subspan(S.m_iMaterial, 1)[0]).m_Instance;
                    Sub.m_Cluster.resize(S.m_nCluster);

                    auto ClusterSpan = Geom.getClusters().subspan(S.m_iCluster, S.m_nCluster);
                    for (auto& C : ClusterSpan)
                    {
                        auto& Cluster = Sub.m_Cluster[static_cast<int>(&C - ClusterSpan.data())];

                        Cluster.m_nFaces    = C.m_nIndices / 3;
                        Cluster.m_nVertices = C.m_nVertices;
                        Cluster.m_BBox      = C.m_BBox;

                        Sub.m_nFaces    += Cluster.m_nFaces;
                        Sub.m_nVertices += Cluster.m_nVertices;
                    }

                    LOD.m_nFaces    += Sub.m_nFaces;
                    LOD.m_nVertices += Sub.m_nVertices;
                    LOD.m_nClusters += static_cast<int>(Sub.m_Cluster.size());
                }

                Mesh.m_nFaces     += LOD.m_nFaces;
                Mesh.m_nVertices  += LOD.m_nVertices;
                Mesh.m_nClusters  += LOD.m_nClusters;
                Mesh.m_nMaterials += static_cast<int>(LOD.m_Submesh.size());
            }
        }

        Size.setup(0);
        for (auto& M : Meshes) Size = Size.Max(M.m_BBox.getSize());
    }
}

#endif // XEDITOR_GEOM_FACTS_H
