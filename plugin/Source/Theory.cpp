#include "Theory.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace sl
{
namespace
{
constexpr const char* noteNames[] = { "C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B" };

constexpr int typeIntervals[4][3] = { { 0, 3, 6 }, { 0, 3, 7 }, { 0, 4, 7 }, { 0, 5, 7 } }; // dim min maj sus
constexpr int extensionInterval[4] = { 9, 10, 11, 14 };                                     // 6 m7 M7 9

constexpr int majorDegrees[7] = { 0, 2, 4, 5, 7, 9, 11 };
constexpr int majorTypes[7]   = { Maj, Min, Min, Maj, Maj, Min, Dim };
constexpr int minorDegrees[7] = { 0, 2, 3, 5, 7, 8, 10 };
constexpr int minorTypes[7]   = { Min, Dim, Maj, Min, Min, Maj, Maj };

constexpr uint32_t bits (std::initializer_list<int> ivs)
{
    uint32_t m = 0;
    for (auto i : ivs) m |= 1u << i;
    return m;
}

struct Suffix { uint32_t mask; const char* text; };

// Interval set -> chord suffix. Mirrors _SUFFIXES in lirio_proto/theory.py.
const Suffix suffixes[] = {
    { bits ({ 0 }), "" },
    { bits ({ 0, 4, 7 }), "" }, { bits ({ 0, 3, 7 }), "m" }, { bits ({ 0, 3, 6 }), "dim" }, { bits ({ 0, 5, 7 }), "sus4" },
    { bits ({ 0, 4, 7, 9 }), "6" }, { bits ({ 0, 3, 7, 9 }), "m6" }, { bits ({ 0, 3, 6, 9 }), "dim7" }, { bits ({ 0, 5, 7, 9 }), "6sus4" },
    { bits ({ 0, 4, 7, 10 }), "7" }, { bits ({ 0, 3, 7, 10 }), "m7" }, { bits ({ 0, 3, 6, 10 }), "m7b5" }, { bits ({ 0, 5, 7, 10 }), "7sus4" },
    { bits ({ 0, 4, 7, 11 }), "maj7" }, { bits ({ 0, 3, 7, 11 }), "m(maj7)" }, { bits ({ 0, 3, 6, 11 }), "dim(maj7)" },
    { bits ({ 0, 5, 7, 11 }), "maj7sus4" },
    { bits ({ 0, 4, 7, 10, 14 }), "9" }, { bits ({ 0, 3, 7, 10, 14 }), "m9" }, { bits ({ 0, 3, 6, 10, 14 }), "m9b5" },
    { bits ({ 0, 5, 7, 10, 14 }), "9sus4" },
    { bits ({ 0, 4, 7, 11, 14 }), "maj9" }, { bits ({ 0, 3, 7, 11, 14 }), "m(maj9)" }, { bits ({ 0, 5, 7, 11, 14 }), "maj9sus4" },
    { bits ({ 0, 4, 7, 9, 14 }), "6/9" }, { bits ({ 0, 3, 7, 9, 14 }), "m6/9" }, { bits ({ 0, 5, 7, 9, 14 }), "6/9sus4" },
    { bits ({ 0, 3, 6, 9, 14 }), "dim7(9)" },
    { bits ({ 0, 4, 7, 9, 10 }), "7(13)" }, { bits ({ 0, 3, 7, 9, 10 }), "m7(13)" }, { bits ({ 0, 3, 6, 9, 10 }), "dim7" },
    { bits ({ 0, 4, 7, 9, 11 }), "maj7(13)" }, { bits ({ 0, 3, 7, 9, 11 }), "m(maj7)(13)" },
    { bits ({ 0, 4, 7, 10, 11 }), "7(maj7)" }, { bits ({ 0, 3, 7, 10, 11 }), "m7(maj7)" },
    { bits ({ 0, 4, 7, 9, 10, 14 }), "13" }, { bits ({ 0, 3, 7, 9, 10, 14 }), "m13" },
    { bits ({ 0, 4, 7, 9, 11, 14 }), "maj13" }, { bits ({ 0, 3, 7, 9, 11, 14 }), "m(maj13)" },
    { bits ({ 0, 4, 7, 10, 11, 14 }), "9(maj7)" }, { bits ({ 0, 3, 7, 10, 11, 14 }), "m9(maj7)" },
    { bits ({ 0, 4, 7, 9, 10, 11, 14 }), "13(maj7)" }, { bits ({ 0, 3, 7, 9, 10, 11, 14 }), "m13(maj7)" },
};

int mod12 (int n) { return ((n % 12) + 12) % 12; }
}

//==============================================================================
template <int Capacity>
void SmallList<Capacity>::sort()
{
    std::sort (data.begin(), data.begin() + size);
}

template struct SmallList<16>;
template struct SmallList<24>;

bool ButtonStack::contains (int b) const
{
    for (int i = 0; i < count; ++i)
        if (order[(size_t) i] == b) return true;
    return false;
}

void ButtonStack::push (int b)
{
    remove (b);
    if (count < NumButtons)
        order[(size_t) count++] = (int8_t) b;
}

void ButtonStack::remove (int b)
{
    int w = 0;
    for (int i = 0; i < count; ++i)
        if (order[(size_t) i] != b)
            order[(size_t) w++] = order[(size_t) i];
    count = w;
}

uint32_t ButtonStack::mask() const
{
    uint32_t m = 0;
    for (int i = 0; i < count; ++i) m |= 1u << order[(size_t) i];
    return m;
}

//==============================================================================
Intervals chordIntervals (const ButtonStack& held, Playstyle style, int defaultType)
{
    SmallList<4> types, exts;
    for (int i = 0; i < held.count; ++i)
    {
        const int b = held.order[(size_t) i];
        if (isType (b)) types.add (b); else exts.add (b);
    }

    // Simple: newest type + newest extension. Advanced: newest type + all extensions.
    if (style != Playstyle::Free && types.size > 1) { types.data[0] = types.data[(size_t) types.size - 1]; types.size = 1; }
    if (style == Playstyle::Simple && exts.size > 1) { exts.data[0] = exts.data[(size_t) exts.size - 1]; exts.size = 1; }

    if (types.size == 0 && defaultType >= 0)
        types.add (defaultType);

    uint32_t m = 0;
    if (types.size == 0 && exts.size == 0)
        m = 1;
    else
    {
        if (types.size == 0)
            types.add (Maj); // extensions without a type sit on a major triad

        for (int i = 0; i < types.size; ++i)
            for (int iv : typeIntervals[types[i]]) m |= 1u << iv;

        bool has6 = false, hasM7 = false, has9 = false, hasDim = false;
        for (int i = 0; i < exts.size; ++i)
        {
            m |= 1u << extensionInterval[exts[i] - Six];
            has6 |= exts[i] == Six; hasM7 |= exts[i] == Maj7; has9 |= exts[i] == Nine;
        }
        for (int i = 0; i < types.size; ++i) hasDim |= types[i] == Dim;

        if (style != Playstyle::Free)
        {
            if (has9 && ! has6 && ! hasM7) m |= 1u << 10; // 9 implies a minor 7th
            if (hasDim && has6)            m |= 1u << 9;  // dim + 6 = dim7
        }
    }

    Intervals out;
    for (int i = 0; i < 16; ++i)
        if (m & (1u << i)) out.add (i);
    return out;
}

void keyModeChord (int note, int keyRoot, bool minor, int& rootOut, int& typeOut)
{
    const int* degrees = minor ? minorDegrees : majorDegrees;
    const int* types   = minor ? minorTypes : majorTypes;
    const int rel = mod12 (note - keyRoot);
    int best = 0;
    for (int i = 0; i < 7; ++i)
        if (degrees[i] <= rel) best = i;
    rootOut = note - (rel - degrees[best]);
    typeOut = types[best];
}

NoteList applyVoicing (int root, const Intervals& ivs, int voicing, bool splitMode)
{
    NoteList notes;
    for (int i = 0; i < ivs.size; ++i) notes.add (root + ivs[i]);
    notes.sort();
    if (notes.size <= 1)
        return notes;

    if (splitMode)
    {
        const int split = root + voicing;
        NoteList folded;
        for (int i = 0; i < notes.size; ++i)
        {
            const int n = split + mod12 (notes[i] - split);
            if (! folded.contains (n)) folded.add (n);
        }
        folded.sort();
        notes = folded;
    }
    else
    {
        for (int step = 0; step < std::abs (voicing); ++step)
        {
            if (voicing > 0)
            {
                const int low = notes[0];
                for (int i = 0; i < notes.size - 1; ++i) notes[i] = notes[i + 1];
                notes[notes.size - 1] = low + 12;
            }
            else
            {
                const int high = notes[notes.size - 1];
                for (int i = notes.size - 1; i > 0; --i) notes[i] = notes[i - 1];
                notes[0] = high - 12;
            }
            notes.sort();
        }
    }

    for (int i = 0; i < notes.size; ++i)
    {
        while (notes[i] < 12)  notes[i] += 12;
        while (notes[i] > 120) notes[i] -= 12;
    }
    notes.sort();
    return notes;
}

int bassNote (int root, const Intervals& ivs, int bassVoicing)
{
    SmallList<12> tones;
    for (int i = 0; i < ivs.size; ++i)
        if (! tones.contains (ivs[i] % 12)) tones.add (ivs[i] % 12);
    tones.sort();

    const int n = tones.size;
    const int octave = (int) std::floor ((double) bassVoicing / n);
    const int idx = ((bassVoicing % n) + n) % n;
    int note = 36 + mod12 (root - 36) + tones[idx] + 12 * octave;
    while (note < 24) note += 12;
    while (note > 64) note -= 12;
    return note;
}

void chordName (int root, const Intervals& ivs, char* out, int outSize)
{
    uint32_t m = 0;
    for (int i = 0; i < ivs.size; ++i) m |= 1u << ivs[i];
    for (const auto& s : suffixes)
    {
        if (s.mask == m)
        {
            std::snprintf (out, (size_t) outSize, "%s%s", noteName (root), s.text);
            return;
        }
    }
    std::snprintf (out, (size_t) outSize, "%s WTF", noteName (root));
}

const char* noteName (int midiNote)
{
    return noteNames[mod12 (midiNote)];
}
}
