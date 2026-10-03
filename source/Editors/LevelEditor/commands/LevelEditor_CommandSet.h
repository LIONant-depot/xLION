#ifndef LevelEditor_COMMAND_SET_H
#define LevelEditor_COMMAND_SET_H
#pragma once

#include "dependencies/xlog/source/xlog_commands.h"

// The editor's commands, in two sets. Constructing a command registers it with the xundo system it is given.
//
//  command_set        the workspace commands (assets, source control, compile, Play/Save/Close, ...), built once at
//                     startup. Those that act on "the Level the user is working on" are re-aimed at the active Level
//                     editor with SetLevelTarget whenever it changes.
//  level_command_set  the commands addressed to one Level by name (Name\Command: entities, scenes, properties, ...),
//                     built for each Level editor as it opens and registered on that editor's own undo system.
// Meant to be included after the command headers (see LevelEditor_App.h).

namespace level_editor
{
    struct level_command_set
    {
        xlevel::commands::save_query_cmd                    CmdSessionSave;       // Name\Save: saves this Level (the Scenes it may write)
        xlevel::commands::close_query_cmd                   CmdSessionClose;      // Name\Close
        xscene::commands::select_cmd                        CmdSelect;
        xscene::commands::toggle_multi_select_cmd           CmdToggleMultiSelect;
        xscene::commands::clear_selection_cmd               CmdClearSelection;
        xscene::commands::rename_entity_cmd                 CmdRenameEntity;
        xscene::commands::set_property_cmd                  CmdSetProperty;
        xscene::commands::snapshot_edit_cmd                 CmdSnapshotEdit;
        xscene::commands::translate_cmd                     CmdTranslate;
        xscene::commands::rotate_cmd                        CmdRotate;
        xscene::commands::scale_cmd                         CmdScale;
        xscene::commands::revert_override_cmd               CmdRevertOverride;
        xscene::commands::apply_overrides_cmd               CmdApplyOverrides;
        xscene::commands::revert_hierarchy_overrides_cmd    CmdRevertHierarchyOverrides;
        xscene::commands::revert_all_overrides_cmd          CmdRevertAllOverrides;
        xscene::commands::add_component_cmd                 CmdAddComponent;
        xscene::commands::remove_component_cmd              CmdRemoveComponent;
        xscene::commands::create_entity_cmd                 CmdCreateEntity;
        xscene::commands::delete_entity_cmd                 CmdDeleteEntity;
        xlevel::commands::close_scene_cmd                   CmdCloseScene;
        xlevel::commands::add_scene_cmd                     CmdAddScene;
        xlevel::commands::remove_scene_cmd                  CmdRemoveScene;
        xlevel::commands::add_scene_dependency_cmd          CmdAddSceneDependency;
        xlevel::commands::remove_scene_dependency_cmd       CmdRemoveSceneDependency;
        xresource_editor::commands::add_library_dependency_cmd        CmdAddLibraryDependency;
        xresource_editor::commands::remove_library_dependency_cmd     CmdRemoveLibraryDependency;
        xlevel::commands::list_scenes_query_cmd             CmdListScenes;
        xlevel::commands::list_entities_query_cmd           CmdListEntities;
        xlevel::commands::list_folders_query_cmd            CmdListFolders;
        xlevel::commands::audit_component_usage_query_cmd   CmdAuditComponentUsage;
        xlevel::commands::undo_query_cmd                    CmdLevelUndo;
        xlevel::commands::redo_query_cmd                    CmdLevelRedo;
        level_editor::commands::serialize_roundtrip_query_cmd     CmdSerializeRoundtrip;
        xlevel::commands::describe_entity_query_cmd         CmdDescribeEntity;
        xlevel::commands::list_component_types_query_cmd    CmdListComponentTypes;
        xlevel::commands::list_systems_query_cmd            CmdListSystems;
        xlevel::commands::set_system_parent_cmd             CmdSetSystemParent;
        xlevel::commands::save_system_order_cmd             CmdSaveSystemOrder;
        xlevel::commands::game_module_status_cmd            CmdGameModuleStatus;
        xlevel::commands::input_state_cmd                   CmdInputState;
        xlevel::commands::raise_error_cmd                   CmdRaiseError;
        xlevel::commands::simulate_gpu_message_cmd          CmdSimulateGpuMessage;
        xlevel::commands::simulate_crash_cmd                CmdSimulateCrash;
        xlevel::commands::modal_state_cmd                   CmdModalState;
        xlevel::commands::simulate_module_crash_cmd         CmdSimulateModuleCrash;
        xlevel::commands::simulate_snapshot_failure_cmd     CmdSimulateSnapshotFailure;
        xscene::commands::set_entity_reference_cmd          CmdSetEntityReference;
        xlevel::commands::edit_tool_query_cmd               CmdEditTool;
        xscene::commands::instantiate_prefab_cmd            CmdInstantiatePrefab;
        xscene::commands::move_to_folder_cmd                CmdMoveToFolder;
        xscene::commands::create_folder_cmd                 CmdCreateFolder;
        xscene::commands::delete_folder_cmd                 CmdDeleteFolder;
        xscene::commands::make_prefab_cmd                   CmdMakePrefab;
        xscene::commands::make_prefab_variant_cmd           CmdMakePrefabVariant;
        xeditor::camera_cmds::set_cmd                       CmdSetCamera;          // Name\SetCamera / GetCamera: the viewport's camera, placed the way the mouse would
        xeditor::camera_cmds::get_cmd                       CmdGetCamera;
        xlevel::commands::set_time_scale_cmd                CmdSetTimeScale;       // Name\SetTimeScale / GetTimeScale: the speed slider next to Play
        xlevel::commands::get_time_scale_cmd                CmdGetTimeScale;

        level_command_set(xundo::system& Level, xscene::scene_context* pScene, xlevel::level_context* pEditor, xeditor::camera_access Camera) noexcept
        : CmdSetCamera(Level, Camera)
        , CmdGetCamera(Level, Camera)
        , CmdSetTimeScale(Level, pEditor)
        , CmdGetTimeScale(Level, pEditor)
        , CmdSessionSave(Level, pEditor)
        , CmdSessionClose(Level, pEditor)
        , CmdSelect(Level, pScene)
        , CmdToggleMultiSelect(Level, pScene)
        , CmdClearSelection(Level, pScene)
        , CmdRenameEntity(Level, pScene)
        , CmdSetProperty(Level, pScene)
        , CmdSnapshotEdit(Level, pScene)
        , CmdTranslate(Level, pScene)
        , CmdRotate(Level, pScene)
        , CmdScale(Level, pScene)
        , CmdRevertOverride(Level, pScene)
        , CmdApplyOverrides(Level, pScene)
        , CmdRevertHierarchyOverrides(Level, pScene)
        , CmdRevertAllOverrides(Level, pScene)
        , CmdAddComponent(Level, pScene)
        , CmdRemoveComponent(Level, pScene)
        , CmdCreateEntity(Level, pScene)
        , CmdDeleteEntity(Level, pScene)
        , CmdCloseScene(Level, pEditor)
        , CmdAddScene(Level, pEditor)
        , CmdRemoveScene(Level, pEditor)
        , CmdAddSceneDependency(Level, pEditor)
        , CmdRemoveSceneDependency(Level, pEditor)
        , CmdAddLibraryDependency(Level, pEditor)
        , CmdRemoveLibraryDependency(Level, pEditor)
        , CmdListScenes(Level, pEditor)
        , CmdListEntities(Level, pEditor)
        , CmdListFolders(Level, pEditor)
        , CmdAuditComponentUsage(Level, pEditor)
        , CmdLevelUndo(Level, pEditor)
        , CmdLevelRedo(Level, pEditor)
        , CmdSerializeRoundtrip(Level, pEditor)
        , CmdDescribeEntity(Level, pEditor)
        , CmdListComponentTypes(Level, pEditor)
        , CmdListSystems(Level, pEditor)
        , CmdSetSystemParent(Level, pEditor)
        , CmdSaveSystemOrder(Level, pEditor)
        , CmdGameModuleStatus(Level, pEditor)
        , CmdInputState(Level, pEditor)
        , CmdRaiseError(Level, pEditor)
        , CmdSimulateGpuMessage(Level, pEditor)
        , CmdSimulateCrash(Level, pEditor)
        , CmdModalState(Level, pEditor)
        , CmdSimulateModuleCrash(Level, pEditor)
        , CmdSimulateSnapshotFailure(Level, pEditor)
        , CmdSetEntityReference(Level, pScene)
        , CmdEditTool(Level, pEditor)
        , CmdInstantiatePrefab(Level, pScene)
        , CmdMoveToFolder(Level, pScene)
        , CmdCreateFolder(Level, pScene)
        , CmdDeleteFolder(Level, pScene)
        , CmdMakePrefab(Level, pScene)
        , CmdMakePrefabVariant(Level, pScene)
        {}
    };

    struct command_set
    {
        level_editor::commands::open_resource_editor_cmd          CmdOpenResourceEditor;
        level_editor::commands::open_type_source_cmd              CmdOpenTypeSource;
        level_editor::commands::resource_editor_command_cmd       CmdResourceEditorCommand;
        level_editor::commands::close_resource_editor_cmd         CmdCloseResourceEditor;
        level_editor::commands::capture_window_cmd                CmdCaptureWindow;
        level_editor::commands::say_query_cmd                     CmdSay;
        level_editor::commands::get_log_query_cmd                 CmdGetLog;
        level_editor::commands::exit_query_cmd                    CmdExit;
        level_editor::commands::list_actions_query_cmd            CmdListActions;
        level_editor::commands::list_gestures_query_cmd           CmdListGestures;
        level_editor::commands::list_keymaps_query_cmd            CmdListKeymaps;
        level_editor::commands::use_keymap_query_cmd              CmdUseKeymap;
        level_editor::commands::save_keymap_as_query_cmd          CmdSaveKeymapAs;
        level_editor::commands::run_action_query_cmd              CmdRunAction;
        level_editor::commands::action_problems_query_cmd         CmdActionProblems;
        level_editor::commands::bind_key_query_cmd                CmdBindKey;
        level_editor::commands::reset_key_query_cmd               CmdResetKey;
        level_editor::commands::press_keys_query_cmd              CmdPressKeys;
        level_editor::commands::explain_last_key_query_cmd        CmdExplainLastKey;
        xlevel::commands::open_level_cmd                    CmdOpenLevel;
        xresource_editor::commands::create_library_query_cmd          CmdCreateLibrary;
        xresource_editor::commands::list_legal_reference_libraries_query_cmd CmdListLegalReferenceLibraries;
        xresource_editor::commands::list_libraries_query_cmd          CmdListLibraries;
        xlevel::commands::list_levels_query_cmd             CmdListLevels;
        xlevel::commands::undo_query_cmd                    CmdUndo;
        xlevel::commands::redo_query_cmd                    CmdRedo;
        xlevel::commands::save_query_cmd                    CmdSave;
        xlevel::commands::close_query_cmd                   CmdClose;
        xlevel::commands::play_query_cmd                    CmdPlay;
        xlevel::commands::pause_query_cmd                   CmdPause;
        xlevel::commands::step_query_cmd                    CmdStep;
        xlevel::commands::stop_query_cmd                    CmdStop;
        xlevel::commands::get_play_state_query_cmd          CmdGetPlayState;
        xlog::commands::command_set                        CmdLogs;     // LogStatus, LogOperations, LogProblems, LogProblem, LogEvents, LogEvent, ...
        xresource_editor::commands::list_assets_query_cmd             CmdListAssets;
        xresource_editor::commands::describe_asset_query_cmd          CmdDescribeAsset;
        xresource_editor::commands::rename_asset_cmd                  CmdRenameAsset;
        xresource_editor::commands::move_asset_cmd                    CmdMoveAsset;
        xresource_editor::commands::delete_asset_cmd                  CmdDeleteAsset;
        xresource_editor::commands::restore_asset_cmd                 CmdRestoreAsset;
        xresource_editor::commands::create_asset_cmd                  CmdCreateAsset;
        xresource_editor::commands::save_assets_query_cmd             CmdSaveAssets;
        level_editor::commands::add_script_source_file_cmd        CmdAddScriptSourceFile;
        level_editor::commands::remove_script_source_file_cmd     CmdRemoveScriptSourceFile;
        level_editor::commands::list_script_source_files_query_cmd CmdListScriptSourceFiles;
        level_editor::commands::add_project_module_reference_cmd  CmdAddProjectModuleReference;
        level_editor::commands::remove_project_module_reference_cmd CmdRemoveProjectModuleReference;
        level_editor::commands::list_project_module_references_query_cmd CmdListProjectModuleReferences;
        level_editor::commands::set_script_source_file_content_cmd CmdSetScriptSourceFileContent;
        level_editor::commands::rename_script_source_file_cmd     CmdRenameScriptSourceFile;
        level_editor::commands::rescan_script_module_cmd          CmdRescanScriptModule;
        level_editor::commands::set_project_game_cmd              CmdSetProjectGame;
        level_editor::commands::set_level_game_cmd                CmdSetLevelGame;
        level_editor::commands::get_level_game_query_cmd          CmdGetLevelGame;
        level_editor::commands::list_module_registrations_query_cmd CmdListModuleRegistrations;
        level_editor::commands::list_scene_modules_query_cmd      CmdListSceneModules;
        level_editor::commands::check_game_compatibility_query_cmd CmdCheckGameCompatibility;
        level_editor::commands::list_scenes_using_module_query_cmd CmdListScenesUsingModule;
        level_editor::commands::regenerate_project_module_sources_query_cmd CmdRegenerateProjectModuleSources;
        xresource_editor::commands::rename_asset_file_cmd             CmdRenameAssetFile;
        xresource_editor::commands::move_asset_file_cmd               CmdMoveAssetFile;
        xresource_editor::commands::delete_asset_file_cmd             CmdDeleteAssetFile;
        xresource_editor::commands::restore_asset_file_cmd            CmdRestoreAssetFile;
        xresource_editor::commands::copy_asset_file_cmd               CmdCopyAssetFile;
        xresource_editor::commands::recompile_all_query_cmd           CmdRecompileAll;
        xresource_editor::commands::recompile_errors_query_cmd        CmdRecompileErrors;
        xresource_editor::commands::compile_start_query_cmd           CmdCompileStart;
        xresource_editor::commands::compile_pause_query_cmd           CmdCompilePause;
        xresource_editor::commands::compile_auto_query_cmd            CmdCompileAuto;
        xresource_editor::commands::compile_status_query_cmd          CmdCompileStatus;
        xlevel::commands::run_sanity_check_query_cmd        CmdRunSanityCheck;
        xlevel::commands::get_idle_tasks_query_cmd          CmdGetIdleTasks;
        xresource_editor::commands::source_control_status_query_cmd   CmdSourceControlStatus;
        xresource_editor::commands::source_control_depot_status_query_cmd CmdSourceControlDepotStatus;
        xresource_editor::commands::source_control_refresh_query_cmd  CmdSourceControlRefresh;
        xresource_editor::commands::source_control_list_locks_query_cmd CmdSourceControlListLocks;
        xresource_editor::commands::source_control_lock_query_cmd     CmdSourceControlLock;
        xresource_editor::commands::source_control_unlock_query_cmd   CmdSourceControlUnlock;
        xresource_editor::commands::source_control_revert_query_cmd   CmdSourceControlRevert;
        xresource_editor::commands::source_control_stage_query_cmd    CmdSourceControlStage;
        xresource_editor::commands::source_control_commit_query_cmd   CmdSourceControlCommit;
        xresource_editor::commands::source_control_pull_query_cmd     CmdSourceControlPull;
        xresource_editor::commands::source_control_push_query_cmd     CmdSourceControlPush;

        command_set(xundo::system& Workspace, xlevel::level_context* pEditor) noexcept
        : CmdOpenResourceEditor(Workspace, pEditor)
        , CmdOpenTypeSource(Workspace, pEditor)
        , CmdResourceEditorCommand(Workspace, pEditor)
        , CmdCloseResourceEditor(Workspace, pEditor)
        , CmdCaptureWindow(Workspace, pEditor)
        , CmdSay(Workspace, pEditor)
        , CmdGetLog(Workspace, pEditor)
        , CmdExit(Workspace, pEditor)
        , CmdListActions(Workspace, pEditor)
        , CmdListGestures(Workspace, pEditor)
        , CmdListKeymaps(Workspace, pEditor)
        , CmdUseKeymap(Workspace, pEditor)
        , CmdSaveKeymapAs(Workspace, pEditor)
        , CmdRunAction(Workspace, pEditor)
        , CmdActionProblems(Workspace, pEditor)
        , CmdBindKey(Workspace, pEditor)
        , CmdResetKey(Workspace, pEditor)
        , CmdPressKeys(Workspace, pEditor)
        , CmdExplainLastKey(Workspace, pEditor)
        , CmdOpenLevel(Workspace, pEditor)
        , CmdCreateLibrary(Workspace, pEditor)
        , CmdListLegalReferenceLibraries(Workspace, pEditor)
        , CmdListLibraries(Workspace, pEditor)
        , CmdListLevels(Workspace, pEditor)
        , CmdUndo(Workspace, pEditor)
        , CmdRedo(Workspace, pEditor)
        , CmdSave(Workspace, pEditor)
        , CmdClose(Workspace, pEditor)
        , CmdPlay(Workspace, pEditor)
        , CmdPause(Workspace, pEditor)
        , CmdStep(Workspace, pEditor)
        , CmdStop(Workspace, pEditor)
        , CmdGetPlayState(Workspace, pEditor)
        , CmdLogs(Workspace, []() -> xlog::view_state* { auto* pHost = xeditor::host::current(); return pHost ? &pHost->m_LogsUi : nullptr; }
                                                                  , []() { auto* pHost = xeditor::host::current(); return pHost && pHost->logs_back(); }
                                                                  , []() { auto* pHost = xeditor::host::current(); return pHost && pHost->logs_forward(); }
                                                                  , [](const std::string& Query) { if (auto* pHost = xeditor::host::current()) pHost->show_logs(Query); })
        , CmdListAssets(Workspace, pEditor)
        , CmdDescribeAsset(Workspace, pEditor)
        , CmdRenameAsset(Workspace, pEditor)
        , CmdMoveAsset(Workspace, pEditor)
        , CmdDeleteAsset(Workspace, pEditor)
        , CmdRestoreAsset(Workspace, pEditor)
        , CmdCreateAsset(Workspace, pEditor)
        , CmdSaveAssets(Workspace, pEditor)
        , CmdAddScriptSourceFile(Workspace, pEditor)
        , CmdRemoveScriptSourceFile(Workspace, pEditor)
        , CmdListScriptSourceFiles(Workspace, pEditor)
        , CmdAddProjectModuleReference(Workspace, pEditor)
        , CmdRemoveProjectModuleReference(Workspace, pEditor)
        , CmdListProjectModuleReferences(Workspace, pEditor)
        , CmdSetScriptSourceFileContent(Workspace, pEditor)
        , CmdRenameScriptSourceFile(Workspace, pEditor)
        , CmdRescanScriptModule(Workspace, pEditor)
        , CmdSetProjectGame(Workspace, pEditor)
        , CmdSetLevelGame(Workspace, pEditor)
        , CmdGetLevelGame(Workspace, pEditor)
        , CmdListModuleRegistrations(Workspace, pEditor)
        , CmdListSceneModules(Workspace, pEditor)
        , CmdCheckGameCompatibility(Workspace, pEditor)
        , CmdListScenesUsingModule(Workspace, pEditor)
        , CmdRegenerateProjectModuleSources(Workspace, pEditor)
        , CmdRenameAssetFile(Workspace, pEditor)
        , CmdMoveAssetFile(Workspace, pEditor)
        , CmdDeleteAssetFile(Workspace, pEditor)
        , CmdRestoreAssetFile(Workspace, pEditor)
        , CmdCopyAssetFile(Workspace, pEditor)
        , CmdRecompileAll(Workspace, pEditor)
        , CmdRecompileErrors(Workspace, pEditor)
        , CmdCompileStart(Workspace, pEditor)
        , CmdCompilePause(Workspace, pEditor)
        , CmdCompileAuto(Workspace, pEditor)
        , CmdCompileStatus(Workspace, pEditor)
        , CmdRunSanityCheck(Workspace, pEditor)
        , CmdGetIdleTasks(Workspace, pEditor)
        , CmdSourceControlStatus(Workspace, pEditor)
        , CmdSourceControlDepotStatus(Workspace, pEditor)
        , CmdSourceControlRefresh(Workspace, pEditor)
        , CmdSourceControlListLocks(Workspace, pEditor)
        , CmdSourceControlLock(Workspace, pEditor)
        , CmdSourceControlUnlock(Workspace, pEditor)
        , CmdSourceControlRevert(Workspace, pEditor)
        , CmdSourceControlStage(Workspace, pEditor)
        , CmdSourceControlCommit(Workspace, pEditor)
        , CmdSourceControlPull(Workspace, pEditor)
        , CmdSourceControlPush(Workspace, pEditor)
        {}

        // Aims the workspace commands at the Level editor the user is working on (the ones that do not act on a Level ignore it).
        void SetLevelTarget(xlevel::level_context* pEditor) noexcept
        {
            CmdOpenResourceEditor.m_pDataBase = pEditor;
            CmdOpenTypeSource.m_pDataBase = pEditor;
            CmdResourceEditorCommand.m_pDataBase = pEditor;
            CmdCloseResourceEditor.m_pDataBase = pEditor;
            CmdCaptureWindow.m_pDataBase = pEditor;
            CmdSay.m_pDataBase = pEditor;
            CmdGetLog.m_pDataBase = pEditor;
            CmdExit.m_pDataBase = pEditor;
            CmdListActions.m_pDataBase = pEditor;
            CmdListGestures.m_pDataBase = pEditor;
            CmdListKeymaps.m_pDataBase = pEditor;
            CmdUseKeymap.m_pDataBase = pEditor;
            CmdSaveKeymapAs.m_pDataBase = pEditor;
            CmdRunAction.m_pDataBase = pEditor;
            CmdActionProblems.m_pDataBase = pEditor;
            CmdBindKey.m_pDataBase = pEditor;
            CmdResetKey.m_pDataBase = pEditor;
            CmdPressKeys.m_pDataBase = pEditor;
            CmdExplainLastKey.m_pDataBase = pEditor;
            CmdOpenLevel.m_pDataBase = pEditor;
            CmdCreateLibrary.m_pDataBase = pEditor;
            CmdListLegalReferenceLibraries.m_pDataBase = pEditor;
            CmdListLibraries.m_pDataBase = pEditor;
            CmdListLevels.m_pDataBase = pEditor;
            CmdUndo.m_pDataBase = pEditor;
            CmdRedo.m_pDataBase = pEditor;
            CmdSave.m_pDataBase = pEditor;
            CmdClose.m_pDataBase = pEditor;
            CmdPlay.m_pDataBase = pEditor;
            CmdPause.m_pDataBase = pEditor;
            CmdStep.m_pDataBase = pEditor;
            CmdStop.m_pDataBase = pEditor;
            CmdGetPlayState.m_pDataBase = pEditor;
            CmdListAssets.m_pDataBase = pEditor;
            CmdDescribeAsset.m_pDataBase = pEditor;
            CmdRenameAsset.m_pDataBase = pEditor;
            CmdMoveAsset.m_pDataBase = pEditor;
            CmdDeleteAsset.m_pDataBase = pEditor;
            CmdRestoreAsset.m_pDataBase = pEditor;
            CmdCreateAsset.m_pDataBase = pEditor;
            CmdSaveAssets.m_pDataBase = pEditor;
            CmdAddScriptSourceFile.m_pDataBase = pEditor;
            CmdRemoveScriptSourceFile.m_pDataBase = pEditor;
            CmdListScriptSourceFiles.m_pDataBase = pEditor;
            CmdAddProjectModuleReference.m_pDataBase = pEditor;
            CmdRemoveProjectModuleReference.m_pDataBase = pEditor;
            CmdListProjectModuleReferences.m_pDataBase = pEditor;
            CmdSetScriptSourceFileContent.m_pDataBase = pEditor;
            CmdRenameScriptSourceFile.m_pDataBase = pEditor;
            CmdRescanScriptModule.m_pDataBase = pEditor;
            CmdSetProjectGame.m_pDataBase = pEditor;
            CmdSetLevelGame.m_pDataBase = pEditor;
            CmdGetLevelGame.m_pDataBase = pEditor;
            CmdListModuleRegistrations.m_pDataBase = pEditor;
            CmdListSceneModules.m_pDataBase = pEditor;
            CmdCheckGameCompatibility.m_pDataBase = pEditor;
            CmdListScenesUsingModule.m_pDataBase = pEditor;
            CmdRegenerateProjectModuleSources.m_pDataBase = pEditor;
            CmdRenameAssetFile.m_pDataBase = pEditor;
            CmdMoveAssetFile.m_pDataBase = pEditor;
            CmdDeleteAssetFile.m_pDataBase = pEditor;
            CmdRestoreAssetFile.m_pDataBase = pEditor;
            CmdCopyAssetFile.m_pDataBase = pEditor;
            CmdRecompileAll.m_pDataBase = pEditor;
            CmdRecompileErrors.m_pDataBase = pEditor;
            CmdCompileStart.m_pDataBase = pEditor;
            CmdCompilePause.m_pDataBase = pEditor;
            CmdCompileAuto.m_pDataBase = pEditor;
            CmdCompileStatus.m_pDataBase = pEditor;
            CmdRunSanityCheck.m_pDataBase = pEditor;
            CmdGetIdleTasks.m_pDataBase = pEditor;
            CmdSourceControlStatus.m_pDataBase = pEditor;
            CmdSourceControlDepotStatus.m_pDataBase = pEditor;
            CmdSourceControlRefresh.m_pDataBase = pEditor;
            CmdSourceControlListLocks.m_pDataBase = pEditor;
            CmdSourceControlLock.m_pDataBase = pEditor;
            CmdSourceControlUnlock.m_pDataBase = pEditor;
            CmdSourceControlRevert.m_pDataBase = pEditor;
            CmdSourceControlStage.m_pDataBase = pEditor;
            CmdSourceControlCommit.m_pDataBase = pEditor;
            CmdSourceControlPull.m_pDataBase = pEditor;
            CmdSourceControlPush.m_pDataBase = pEditor;
        }
    };
}

#endif // LevelEditor_COMMAND_SET_H
