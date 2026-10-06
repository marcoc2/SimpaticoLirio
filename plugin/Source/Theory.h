#pragma once

#include <array>
#include <cstdint>

// Chord logic, ported from lirio_proto/theory.py (the Python prototype is the reference).
//
// Eight chord buttons:
//     top row (chord types):     DIM  MIN  MAJ  SUS
//     bottom row (extensions):   6    m7   M7   9
namespace sl
{
enum Button : int { Dim, Min, Maj, Sus, Six, Min7, Maj7, Nine, NumButtons };

enum class Playstyle : int { Simple, Advanced, Free };

inline bool isType (int b)      { return b >= Dim && b <= Sus; }
inline bool isExtension (int b) { return b >= Six && b <= Nine; }

/** Buttons in press order (oldest first). */
struct ButtonStack
{
    std::array<int8_t, NumButtons> order {};
    int count = 0;

    bool contains (int b) const;
    void push (int b);
    void remove (int b);
    uint32_t mask() const;
};

/** Small fixed-capacity list of ints, safe for the audio thread. */
template <int Capacity>
struct SmallList
{
    std::array<int, Capacity> data {};
    int size = 0;

    void add (int v)                 { if (size < Capacity) data[(size_t) size++] = v; }
    int operator[] (int i) const     { return data[(size_t) i]; }
    int& operator[] (int i)          { return data[(size_t) i]; }
    bool contains (int v) const      { for (int i = 0; i < size; ++i) if (data[(size_t) i] == v) return true; return false; }
    bool operator== (const SmallList& o) const
    {
        if (size != o.size) return false;
        for (int i = 0; i < size; ++i) if (data[(size_t) i] != o.data[(size_t) i]) return false;
        return true;
    }
    void sort();
};

using Intervals = SmallList<16>;
using NoteList  = SmallList<24>;

/** Intervals (semitones above the root) for the held buttons.
    defaultType is a chord-type Button used when no type button is held (Key Mode), or -1. */
Intervals chordIntervals (const ButtonStack& held, Playstyle style, int defaultType);

/** Key Mode: snap a played note into the key; returns the root and its diatonic chord type. */
void keyModeChord (int note, int keyRoot, bool minor, int& rootOut, int& typeOut);

/** Voicing Dial. Octave mode inverts one note per step; split mode folds the chord tones
    into the octave starting at root + voicing. */
NoteList applyVoicing (int root, const Intervals& ivs, int voicing, bool splitMode);

/** Bass note: root by default, the Bass Voicing Dial walks through the chord tones. */
int bassNote (int root, const Intervals& ivs, int bassVoicing);

/** Writes e.g. "Dm9" or "C WTF" into out (null terminated). */
void chordName (int root, const Intervals& ivs, char* out, int outSize);

const char* noteName (int midiNote);
}
