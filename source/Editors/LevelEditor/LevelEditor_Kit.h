#ifndef LevelEditor_LEVEL_SCENE_EDITOR_KIT_H
#define LevelEditor_LEVEL_SCENE_EDITOR_KIT_H
#pragma once

#include "source/xGPU.h"

#include "dependencies/xmath/source/xmath.h"
#include "dependencies/xproperty/source/xcore/my_properties.h"
#include "dependencies/xproperty/source/examples/imgui/xPropertyImGuiInspector.h"
#include "dependencies/xstrtool/source/xstrtool.h"

#include <algorithm>
#include <filesystem>
#include <format>
#include <functional>
#include <unordered_set>
#include <cctype>
#include <cstring>

// xECSV2 - real Level/Scene resource types (see dependencies/xECSV2/src/xecs_level*.h,
// xecs_scene*.h) and the entity/component machinery this editor edits. Included BEFORE the
// resource-pipeline/asset-browser headers below so xecs.h's own narrow xresource_pipeline_v2
// includes (descriptor_base/info/factory/version - all #pragma once) are the ones that win; the
// asset-browser's own xresource_pipeline.h umbrella pull of the same four headers becomes a no-op.
#include "dependencies/xECSV2/src/xecs.h"
#include "dependencies/xeditor/include/xeditor/commands.h"
#include "dependencies/xeditor/include/xeditor/widgets.h"

#define XRESOURCE_PIPELINE_NO_COMPILER
#include "dependencies/xresource_pipeline_v2/source/xresource_pipeline.h"
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_resources.h"
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_asset_mgr.h"
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_asset_browser.h"
#include "source/Editors/LevelEditor/LevelEditor_EditorTabs.h"

//-----------------------------------------------------------------------------------
// The include order of the editor's translation unit: the scene editor and the Level editor (plugins), the resource commands
// and browser hooks, and the panels of the game module, the command console and source control. The headers are not standalone: order matters.
//-----------------------------------------------------------------------------------

#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_inspector_pickers.h"
#include "plugins/xscene.plugin/source/Editor/xscene_editor.h"
#include "plugins/xlevel.plugin/source/Editor/xlevel_editor.h"

// STAGE (a) of the LevelEditor-ownership move (see plugins/xlevel.plugin's own git history / the task that
// landed this): the new xeditor::resource_editor-shaped Level session, compiled here alongside the
// still-working level_editor::app below so both are checked by every build. It registers a factory but is
// never opened yet (nothing calls ResourceEditors.Open() with xecs::level::type_guid_v) - purely additive,
// zero behavior change until stage (b) flips the shell over and the old in-place rendering is deleted.
#include "plugins/xlevel.plugin/source/Editor/xlevel_session.h"

#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_commands_assets.h"
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_commands_asset_files.h"
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_asset_browser_callbacks.h"

#include "source/Editors/LevelEditor/extensions/command_console/LevelEditor_Panel_CommandConsole.h"
#include "dependencies/xresource_pipeline_v2/source/editor/xresource_editor_panel_source_control.h"

#endif // LevelEditor_LEVEL_SCENE_EDITOR_KIT_H
