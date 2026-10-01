#include "dependencies/xscheduler/source/xscheduler.h"

// xLION - graphical entry point. Full window/Vulkan/ImGui init, today's editor UI.
// See source/main_headless.cpp for the no-window, command-console-only variant.
int RunLevelEditorGraphical();

int main()
{
    // Without this, EnsureLibraryLoaded's process_info_job (xresource_editor_asset_mgr.h) submits work to
    // xscheduler::g_System and then polls its state forever, since no worker thread was ever
    // started to actually process it - hangs the very first OpenProject call during startup,
    // before any window content is ever painted (a "not responding" blank white window, not a
    // crash). xGPU's own source/Examples/main.cpp does this same call before launching any
    // example, for the same reason.
    xscheduler::g_System.Init();
    return RunLevelEditorGraphical();
}
