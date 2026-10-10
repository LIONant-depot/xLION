#pragma once
// <unistd.h> declares the POSIX function link(); a program that has its own type called "link" (xecs has one, and the xECSV2 smoke programs name it unqualified) then
// has to say "struct link" everywhere. Included first (-include) this reads <unistd.h> with that one function under another name, so the type keeps the name it has on Windows.
#define link xlion_posix_link
#include <unistd.h>
#undef link
