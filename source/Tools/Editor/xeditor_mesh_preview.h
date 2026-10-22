#ifndef XEDITOR_MESH_PREVIEW_H
#define XEDITOR_MESH_PREVIEW_H
#pragma once

// A material shown on a primitive (cube, sphere, capsule, cylinder) over a checker background: what the Material and Material Instance editors
// preview with. The editor gives it the material's fragment shader and texture bindings (SetMaterial); the panel calls Render every frame.
#include "source/Examples/E19_MaterialEditor/E19_mesh_manager.h"
#include "source/Tools/Editor/xeditor_camera.h"
#include "source/Tools/Editor/xeditor_camera_toolbar.h"
#include "dependencies/xeditor_tools/src/xeditor_tools_camera.h"
#include "source/Tools/xgpu_imgui_breach.h"
#include "source/Tools/xgpu_view.h"
#include "source/Tools/xgpu_xcore_bitmap_helpers.h"
#include "dependencies/imgui/imgui.h"

#include <array>
#include <cstdio>
#include <span>

namespace xeditor
{
    class mesh_preview
    {
    public:
        // The 2D pipeline the checker background is drawn with, and the vertex shader every previewed material gets
        static constexpr auto s_2DVertShader = std::array
        {
            #include "imgui_vert.h"
        };
        static constexpr auto s_2DFragShader = std::array
        {
            #include "draw_frag.h"
        };
        // A real PBR material (mb_standard_pbr.frag / mb_material_pbr.frag - the common case) needs the full
        // varying interface a plain position/uv/color pass-through can't provide; see the shader's own
        // comment for why it's a separate file instead of draw_vert.glsl (used broadly elsewhere).
        static constexpr auto s_MeshVertShader = std::array
        {
            #include "xeditor_mesh_preview_full_vert.h"
        };

        struct push_const2D
        {
            xmath::fvec2    m_Scale;
            xmath::fvec2    m_Translation;
            xmath::fvec2    m_UVScale;
        };

        // Exactly the guaranteed-minimum 128-byte Vulkan push-constant budget (two mat4s) - no room to spare.
        struct push_constants
        {
            xmath::fmat4    m_L2W;
            xmath::fmat4    m_W2C;
        };

        // Mirrors mb_standard_pbr.frag's "lighting_uniforms" (set 2, binding 1) field for field - a real
        // material's fragment shader reads these for actual shading, not just to satisfy the pipeline layout.
        struct alignas(256) ubo_lighting
        {
            xmath::fvec4    m_LightColor;
            xmath::fvec4    m_AmbientLightColor;
            xmath::fvec4    m_wSpaceLightPos;        // xyz = position, w = falloff radius (0 = infinite)
            xmath::fvec4    m_wSpaceEyePos;
            xmath::fvec4    m_LightParams;           // .x = area radius, .y = temperature (K), .z = intensity mult, .w = spare
        };

        bool Init(xgpu::device& Device) noexcept
        {
            if (m_bReady) return true;
            m_pDevice = &Device;
            m_Meshes.Init(Device);

            auto Attributes = std::array
            { xgpu::vertex_descriptor::attribute{ .m_Offset = offsetof(e19::draw_vert, m_X),     .m_Format = xgpu::vertex_descriptor::format::FLOAT_3D }
            , xgpu::vertex_descriptor::attribute{ .m_Offset = offsetof(e19::draw_vert, m_U),     .m_Format = xgpu::vertex_descriptor::format::FLOAT_2D }
            , xgpu::vertex_descriptor::attribute{ .m_Offset = offsetof(e19::draw_vert, m_Color), .m_Format = xgpu::vertex_descriptor::format::UINT8_4D_NORMALIZED }
            , xgpu::vertex_descriptor::attribute{ .m_Offset = offsetof(e19::draw_vert, m_NX),    .m_Format = xgpu::vertex_descriptor::format::FLOAT_3D }
            , xgpu::vertex_descriptor::attribute{ .m_Offset = offsetof(e19::draw_vert, m_TX),    .m_Format = xgpu::vertex_descriptor::format::FLOAT_4D }
            };
            if (!Ok(Device.Create(m_MeshVD, xgpu::vertex_descriptor::setup{ .m_VertexSize = sizeof(e19::draw_vert), .m_Attributes = Attributes }))) return false;

            if (!Ok(Device.Create(m_LightUBO, { .m_Type = xgpu::buffer::type::UNIFORM, .m_Usage = xgpu::buffer::setup::usage::CPU_WRITE_GPU_READ
                , .m_EntryByteSize = sizeof(ubo_lighting), .m_EntryCount = 4 }))) return false;

            // The background: a textured 2D plane
            xgpu::vertex_descriptor VD2D;
            {
                auto Attributes2D = std::array
                { xgpu::vertex_descriptor::attribute{ .m_Offset = offsetof(e19::vert_2d, m_X),     .m_Format = xgpu::vertex_descriptor::format::FLOAT_2D }
                , xgpu::vertex_descriptor::attribute{ .m_Offset = offsetof(e19::vert_2d, m_U),     .m_Format = xgpu::vertex_descriptor::format::FLOAT_2D }
                , xgpu::vertex_descriptor::attribute{ .m_Offset = offsetof(e19::vert_2d, m_Color), .m_Format = xgpu::vertex_descriptor::format::UINT8_4D_NORMALIZED }
                };
                if (!Ok(Device.Create(VD2D, xgpu::vertex_descriptor::setup{ .m_VertexSize = sizeof(e19::vert_2d), .m_Attributes = Attributes2D }))) return false;
            }

            xgpu::shader Frag, Vert;
            if (!Ok(Device.Create(Frag, { .m_Type = xgpu::shader::type::bit::FRAGMENT, .m_Sharer = xgpu::shader::setup::raw_data{ s_2DFragShader } }))) return false;
            if (!Ok(Device.Create(Vert, { .m_Type = xgpu::shader::type::bit::VERTEX,   .m_Sharer = xgpu::shader::setup::raw_data{ s_2DVertShader } }))) return false;

            auto Shaders  = std::array<const xgpu::shader*, 2>{ &Frag, &Vert };
            auto Samplers = std::array{ xgpu::pipeline::sampler{} };
            if (!Ok(Device.Create(m_Pipeline2D, xgpu::pipeline::setup
                { .m_VertexDescriptor = VD2D, .m_Shaders = Shaders, .m_PushConstantsSize = sizeof(push_const2D), .m_Samplers = Samplers
                , .m_DepthStencil = { .m_bDepthTestEnable = false } }))) return false;

            if (auto* pErr = xgpu::tools::bitmap::Create(m_CheckerTexture, Device, xbitmap::getDefaultBitmap()); pErr) return false;
            if (auto* pErr = xgpu::tools::bitmap::Create(m_DefaultTexture, Device, xbitmap::getDefaultBitmap()); pErr) return false;

            auto Bindings = std::array{ xgpu::pipeline_instance::sampler_binding{ m_CheckerTexture } };
            if (!Ok(Device.Create(m_Background, { .m_PipeLine = m_Pipeline2D, .m_SamplersBindings = Bindings }))) return false;

            m_View.setFov(60_xdeg);
            m_bReady = true;
            return true;
        }

        // What a material slot with no texture of its own is bound to
        xgpu::texture& DefaultTexture() noexcept { return m_DefaultTexture; }

        // The material to show: its fragment shader (with the preview's vertex shader), one binding per sampler it declares and its parameter block (the material's
        // default block, or an instance's resolved one: MaterialParams, binding 9, documentation/material_contract.md section 2). The LDR shader reads it at base 0.
        bool SetMaterial(const xgpu::shader& Fragment, std::span<xgpu::pipeline_instance::sampler_binding> Bindings, std::span<const float> Block = {}) noexcept
        {
            if (!m_bReady) return false;
            ClearMaterial();

            // Binding 9 holds the block (one zero vec4 when there is none: a buffer cannot be empty), binding 10 one zeroed entity entry (mask 0: nothing overridden).
            // ponytail: new buffers per call; the old ones free themselves when dropped.
            std::array<float, 4> Zero{};
            if (Block.empty()) Block = Zero;
            std::array<float, 16> Entity{};
            if (!Ok(m_pDevice->Create(m_Params, { .m_Type = xgpu::buffer::type::STORAGE, .m_Usage = xgpu::buffer::setup::usage::GPU_READ
                , .m_EntryByteSize = 16, .m_EntryCount = int(Block.size() / 4), .m_pData = const_cast<float*>(Block.data()) }))) return false;
            if (!Ok(m_pDevice->Create(m_Entity, { .m_Type = xgpu::buffer::type::STORAGE, .m_Usage = xgpu::buffer::setup::usage::GPU_READ
                , .m_EntryByteSize = 64, .m_EntryCount = 1, .m_pData = Entity.data() }))) return false;

            xgpu::shader Vert;
            if (!Ok(m_pDevice->Create(Vert, { .m_Type = xgpu::shader::type::bit::VERTEX, .m_Sharer = xgpu::shader::setup::raw_data{ s_MeshVertShader } }))) return false;

            std::vector<xgpu::pipeline::sampler> Samplers(Bindings.size());
            auto Shaders = std::array<const xgpu::shader*, 2>{ &Fragment, &Vert };
            // Binding 1 (set 2, per xgpu's uniform_binds convention) - mb_standard_pbr.frag's "lighting_uniforms".
            // A material whose fragment shader doesn't declare it (not built on mb_standard_pbr.frag) simply
            // never reads this bind; declaring it unconditionally costs nothing there.
            auto UniformBinds = std::array
            { xgpu::pipeline::uniform_binds{ .m_BindIndex = 1,  .m_Usage = { .m_bFragment = true }, .m_Type = xgpu::pipeline::uniform_binds::type::UBO_DYNAMIC }
            , xgpu::pipeline::uniform_binds{ .m_BindIndex = 9,  .m_Usage = { .m_bFragment = true }, .m_Type = xgpu::pipeline::uniform_binds::type::SSBO_STATIC }       // MaterialParams
            , xgpu::pipeline::uniform_binds{ .m_BindIndex = 10, .m_Usage = { .m_bFragment = true }, .m_Type = xgpu::pipeline::uniform_binds::type::SSBO_STATIC }       // EntityParams (the LDR shader never reads it)
            };
            if (!Ok(m_pDevice->Create(m_Pipeline, xgpu::pipeline::setup
                { .m_VertexDescriptor = m_MeshVD, .m_Shaders = Shaders, .m_PushConstantsSize = sizeof(push_constants), .m_UniformBinds = UniformBinds, .m_Samplers = Samplers }))) return false;

            if (!Bindings.empty())
                return Ok(m_pDevice->Create(m_Instance, { .m_PipeLine = m_Pipeline, .m_SamplersBindings = Bindings }));

            return Ok(m_pDevice->Create(m_Instance, { .m_PipeLine = m_Pipeline }));
        }

        void ClearMaterial() noexcept
        {
            if (!m_pDevice) return;
            xeditor::DestroyGpu(m_pDevice, m_Instance, m_Pipeline);
        }

        bool hasMaterial() const noexcept { return m_Instance.m_Private != nullptr; }

        ~mesh_preview() noexcept
        {
            ClearMaterial();
            xeditor::DestroyGpu(m_pDevice, m_Background, m_Pipeline2D, m_CheckerTexture, m_DefaultTexture);
        }

        // The panel: a mesh picker over the preview. Right drag turns the object, the wheel zooms.
        void Render() noexcept
        {
            if (!m_bToolbar) { m_bToolbar = true; m_CameraToolbar.Init(reinterpret_cast<std::uint64_t>(this)); }
            m_CameraToolbar.Render(ImGui::GetContentRegionAvail(), m_CameraState, [this] { RenderBody(); });
        }

        void RenderBody() noexcept
        {
            if (!m_bReady) { ImGui::TextDisabled("Preview needs a GPU device (open from LevelEditor)."); return; }

            static constexpr const char* s_Names[] = { "Cube", "Sphere", "Capsule", "Cylinder" };      // keep in step with s_ModelNames
            if (ImGui::Button("\xEE\xAF\x92 Meshes")) ImGui::OpenPopup("Meshes");
            if (ImGui::BeginPopup("Meshes"))
            {
                for (int n = 0; n < IM_ARRAYSIZE(s_Names); ++n)
                    if (ImGui::Selectable(s_Names[n], static_cast<int>(m_Model) == n)) m_Model = static_cast<e19::mesh_manager::model>(n);
                ImGui::EndPopup();
            }

            const ImVec2 Avail = ImGui::GetContentRegionAvail();
            const ImVec2 Min   = ImGui::GetCursorScreenPos();
            ImGui::InvisibleButton("##MeshPreviewCanvas", Avail, ImGuiButtonFlags_MouseButtonLeft | ImGuiButtonFlags_MouseButtonRight | ImGuiButtonFlags_MouseButtonMiddle);
            // The shared camera (xeditor_tools_camera.h): Orbit or Fly, F switches
            {
                const xeditor_tools::camera_rig Rig{ m_CameraState, m_View, m_Angles, m_Distance, m_Target };
                xeditor_tools::HandleCameraInput(Rig);
                m_Distance = std::max(m_Distance, 0.2f);
                if (m_CameraState.m_bFrame) { m_CameraState.m_bFrame = false; m_Distance = 2; m_Target = {}; }        // F in Fly: back on the mesh
            }

            // The callback draws into the clip rectangle it is added with: the canvas
            ImGui::PushClipRect(Min, ImVec2(Min.x + Avail.x, Min.y + Avail.y), true);
            xgpu::tools::imgui::AddCustomRenderCallback([this, Avail](xgpu::cmd_buffer& CmdBuffer, const ImVec2&, const ImVec2&) { Draw(CmdBuffer, Avail.x, Avail.y); });
            ImGui::PopClipRect();
            xeditor_tools::DrawCameraOverlay({ m_CameraState, m_View, m_Angles, m_Distance, m_Target });
        }

    public:     // what the commands of the preview reach
        e19::mesh_manager::model        m_Model   = e19::mesh_manager::model::CUBE;

        static constexpr const char* s_ModelNames[] = { "Cube", "Sphere", "Capsule", "Cylinder" };

        // The camera's numbers, for the camera commands
        xeditor::camera_access Camera() noexcept { return { &m_Angles, &m_Distance, &m_Target, [this] { m_Angles = {}; m_Distance = 2; m_Target = {}; }, &m_CameraState }; }

        // The preview into a render pass that is already open (the panel's, or a thumbnail's own target). Without the background the pass's clear
        // colour shows around the mesh.
        void Draw(xgpu::cmd_buffer& CmdBuffer, float ViewW, float ViewH, bool bBackground = true) noexcept
        {
            if (!m_bReady || ViewW <= 1.f || ViewH <= 1.f) return;
            if (bBackground) DrawBackground(CmdBuffer, ViewW, ViewH);
            if (hasMaterial()) DrawMesh(CmdBuffer, ViewW, ViewH);
        }

    private:
        static bool Ok(xgpu::device::error* pErr) noexcept
        {
            if (!pErr) return true;
            std::printf("Mesh preview: %s\n", std::string(xgpu::getErrorMsg(pErr)).c_str());
            return false;
        }

        void DrawBackground(xgpu::cmd_buffer& CmdBuffer, float ViewW, float ViewH) noexcept
        {
            push_const2D Background;
            Background.m_Scale       = { (150 * 2.0f) / ViewW, (150 * 2.0f) / ViewH };
            Background.m_Translation.setup(0);
            Background.m_UVScale     = { 100.0f, 100.0f };
            CmdBuffer.setPipelineInstance(m_Background);
            CmdBuffer.setPushConstants(Background);
            m_Meshes.Rendering(CmdBuffer, e19::mesh_manager::model::PLANE2D);
        }

        void DrawMesh(xgpu::cmd_buffer& CmdBuffer, float ViewW, float ViewH) noexcept
        {
            m_View.setViewport({ 0, 0, static_cast<int>(ViewW), static_cast<int>(ViewH) });

            // Keep the object inside the view
            const float VerticalFov = m_View.getFov().m_Value;
            const float Aspect      = m_View.getAspect();
            const float Radius      = 0.5f;
            const float HFov        = 2.0f * std::atan(Aspect * std::tan(VerticalFov / 2.0f));
            const float Distance    = Radius / std::tan(std::min(VerticalFov, HFov) / 2.0f);
            m_View.LookAt(m_Distance + Distance - 1, m_Angles, m_Target);

            push_constants PushConst;
            PushConst.m_L2W = xmath::fmat4::fromScale({ 2.f });
            PushConst.m_W2C = m_View.getW2C();

            // A fixed, camera-relative key light (product-shot style: up and to the side of whatever angle
            // the mesh is being viewed from) - there is no scene lighting to draw from in this preview.
            auto& Lighting               = m_LightUBO.allocEntry<ubo_lighting>();
            Lighting.m_LightColor        = xmath::fvec4(1) * 4;
            Lighting.m_AmbientLightColor = xmath::fvec4(1) * 0.7f;
            Lighting.m_wSpaceLightPos    = xmath::fvec4(m_View.getPosition() + xmath::fvec3{ 1, 2, 1 } * m_Distance, 20.f);
            Lighting.m_wSpaceEyePos      = xmath::fvec4(m_View.getPosition(), 0);
            Lighting.m_LightParams       = { 2.f, 6500.f, 1.f, 0.f };  // area radius, temperature (K), intensity mult, spare

            auto Static = std::array<xgpu::buffer*, 2>{ &m_Params, &m_Entity };
            CmdBuffer.setPipelineInstance(m_Instance, Static);
            CmdBuffer.setPushConstants(PushConst);
            CmdBuffer.setDynamicUBO(m_LightUBO, 1);
            m_Meshes.Rendering(CmdBuffer, m_Model);
        }

        xgpu::device*                   m_pDevice = nullptr;
        bool                            m_bReady  = false;
        e19::mesh_manager               m_Meshes;
        xgpu::vertex_descriptor         m_MeshVD;
        xgpu::buffer                    m_LightUBO;
        xgpu::buffer                    m_Params;                            // MaterialParams: the shown material's block
        xgpu::buffer                    m_Entity;                            // EntityParams: one zeroed entry
        xgpu::pipeline                  m_Pipeline2D;
        xgpu::pipeline_instance         m_Background;
        xgpu::texture                   m_CheckerTexture;
        xgpu::texture                   m_DefaultTexture;
        xgpu::pipeline                  m_Pipeline;
        xgpu::pipeline_instance         m_Instance;
        xgpu::tools::view               m_View;
        xmath::radian3                  m_Angles;
        xmath::fvec3                    m_Target = xmath::fvec3(0, 0, 0);    // what the camera looks at: the mesh, until the user moves it
        xeditor_tools::camera_state     m_CameraState;                       // Orbit or Fly
        xeditor::camera_toolbar         m_CameraToolbar;
        bool                            m_bToolbar = false;
        float                           m_Distance = 2;
    };

    // The commands of a mesh preview: which mesh, and the camera
    struct mesh_preview_cmds
    {
        struct mesh_cmd : xundo::query_command_base
        {
            mesh_preview& m_Preview;
            mesh_cmd(xundo::system& System, mesh_preview& Preview) noexcept : query_command_base(System, "SetPreviewMesh", nullptr), m_Preview(Preview) { RegisterArguments(); }
            const char* getCommandHelp() const noexcept override { return "The mesh the material is previewed on (view state; without -Model it says which). Usage: SetPreviewMesh [-Model Cube|Sphere|Capsule|Cylinder]"; }
            void RegisterArguments() noexcept override { m_hModel = m_Parser.addOption("Model", "Cube, Sphere, Capsule or Cylinder", false, 1); }
            std::string Query() noexcept override
            {
                std::string Name;
                if (!cmd_util::GetArg(m_Parser, m_hModel, Name)) return std::format("SetPreviewMesh: {}", mesh_preview::s_ModelNames[static_cast<int>(m_Preview.m_Model)]);
                for (int i = 0; i < 4; ++i)
                    if (Name == mesh_preview::s_ModelNames[i]) { m_Preview.m_Model = static_cast<e19::mesh_manager::model>(i); return std::format("SetPreviewMesh: {}", Name); }
                return "SetPreviewMesh: Model is Cube, Sphere, Capsule or Cylinder";
            }
            xcmdline::parser::handle m_hModel;
        };

        camera_cmds m_Camera;
        mesh_cmd    m_Mesh;

        mesh_preview_cmds(xundo::system& System, mesh_preview& Preview) noexcept : m_Camera(System, Preview.Camera()), m_Mesh(System, Preview) {}
    };
}

#endif // XEDITOR_MESH_PREVIEW_H
