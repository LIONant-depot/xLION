#include "dependencies/xscheduler/source/xscheduler.h"

// xLION - headless entry point. No window, no device, no ImGui. The full command system (ECS,
// undo, asset browser, Command Console pipe) still runs - drive it with xeditorcli or a script
// talking to \\.\pipe\xEditor_Console. See source/main_graphical.cpp for the windowed variant.
int RunLevelEditorHeadless();

int main()
{
    // See source/main_graphical.cpp's own comment - OpenProject needs xscheduler::g_System's
    // worker threads running or it hangs polling a job that's never processed.
    xscheduler::g_System.Init();
    return RunLevelEditorHeadless();
}
