// Prints chord names/notes for every button combination so the output can be diffed
// against the Python prototype (handful_proto/theory.py). Run: HandfulTheoryTest > cpp.txt
#include "../Source/Theory.h"

#include <cstdio>

int main()
{
    using namespace hf;
    const char* styles[] = { "SIMPLE", "ADVANCED", "FREE" };
    for (int style = 0; style < 3; ++style)
        for (int mask = 0; mask < 256; ++mask)
            for (int voicing : { -3, 0, 2, 5 })
                for (int split = 0; split < 2; ++split)
                {
                    ButtonStack held;
                    for (int b = 0; b < NumButtons; ++b)
                        if (mask & (1 << b)) held.push (b);
                    const int root = 57 + (mask % 7);
                    const auto ivs = chordIntervals (held, (Playstyle) style, -1);
                    const auto notes = applyVoicing (root, ivs, voicing, split != 0);
                    char name[32];
                    chordName (root, ivs, name, 32);
                    std::printf ("%s %d %d %d %s |", styles[style], mask, voicing, split, name);
                    for (int i = 0; i < notes.size; ++i) std::printf (" %d", notes[i]);
                    std::printf (" | bass %d %d\n", bassNote (root, ivs, voicing % 5), bassNote (root, ivs, -1));
                }
    // Key mode
    for (int minor = 0; minor < 2; ++minor)
        for (int note = 48; note < 72; ++note)
        {
            int root = 0, type = 0;
            keyModeChord (note, 2, minor != 0, root, type);
            std::printf ("KEY %d %d %d %d\n", minor, note, root, type);
        }
    return 0;
}
