#pragma once
// Linux stand-in for the MSVC debug CRT header and the few process-mode calls that go with it (<stdlib.h>/<windows.h> on Windows): the standalone smoke programs
// (dependencies/xECSV2/smoke_test_*.cpp) call them to keep a failure from waiting on a dialog. There is no dialog on Linux, so they do nothing.
#include <cstdlib>

#define _CRT_WARN                0
#define _CRT_ERROR               1
#define _CRT_ASSERT              2
#define _CRTDBG_MODE_FILE        0x1
#define _CRTDBG_MODE_DEBUG       0x2
#define _CRTDBG_FILE_STDERR      (reinterpret_cast<void*>(-5))
#define _CRTDBG_FILE_STDOUT      (reinterpret_cast<void*>(-4))
#define _WRITE_ABORT_MSG         0x1
#define _CALL_REPORTFAULT        0x2
#define SEM_FAILCRITICALERRORS   0x0001
#define SEM_NOGPFAULTERRORBOX    0x0002
#define SEM_NOOPENFILEERRORBOX   0x8000

inline int          _CrtSetReportMode(int, int)              noexcept { return 0; }
inline void*        _CrtSetReportFile(int, void*)            noexcept { return nullptr; }
inline int          _CrtSetDbgFlag(int)                      noexcept { return 0; }
inline unsigned int _set_abort_behavior(unsigned int, unsigned int) noexcept { return 0; }
inline unsigned int SetErrorMode(unsigned int)               noexcept { return 0; }
