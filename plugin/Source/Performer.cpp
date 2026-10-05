#include "Performer.h"

#include <cmath>

namespace hf
{
namespace
{
struct Rate { const char* name; double sixteenths; };
constexpr Rate rates[] = { { "1/4", 4.0 }, { "1/8", 2.0 }, { "1/8T", 4.0 / 3.0 }, { "1/16", 1.0 }, { "1/16T", 2.0 / 3.0 }, { "1/32", 0.5 } };

// Step codes: -2 rest, -1 whole chord, -3 every tone but the lowest, k = chord tone k (wrapping).
constexpr int R = -2, ALL = -1, UP = -3;
struct Pattern { const char* name; int steps[16]; };
constexpr Pattern patterns[] = {
    { "Pulse",   { ALL, R, R, ALL, R, R, ALL, R, R, R, ALL, R, ALL, R, R, R } },
    { "Alberti", { 0, 2, 1, 2, 0, 2, 1, 2, 0, 2, 1, 2, 0, 2, 1, 2 } },
    { "Bounce",  { 0, R, UP, R, 0, R, UP, UP, 0, R, UP, R, 0, UP, R, UP } },
    { "Offbeat", { R, R, ALL, R, R, R, ALL, R, R, R, ALL, R, R, R, ALL, ALL } },
    { "Ripple",  { 0, 1, 2, 3, 2, 1, 0, R, 0, 1, 2, 3, 4, 3, 2, 1 } },
};
}

const char* Performer::arpRateName (int index) { return rates[juce::jlimit (0, numArpRates - 1, index)].name; }
const char* Performer::patternName (int index) { return patterns[juce::jlimit (0, numPatterns - 1, index)].name; }

//==============================================================================
void Performer::schedule (int64_t time, bool on, int note, int vel)
{
    if (queueSize >= (int) queue.size())
        return;
    // Keep the queue sorted by (time, seq): insert from the back.
    Event e { time, ++seq, on, note, vel };
    int i = queueSize++;
    while (i > 0 && queue[(size_t) i - 1].time > time)
    {
        queue[(size_t) i] = queue[(size_t) i - 1];
        --i;
    }
    queue[(size_t) i] = e;
}

void Performer::cancelPendingNoteOns()
{
    int w = 0;
    for (int i = 0; i < queueSize; ++i)
        if (! queue[(size_t) i].on) queue[(size_t) w++] = queue[(size_t) i];
    queueSize = w;
}

void Performer::noteOn (int note, int vel, int64_t time)
{
    if (note < 0 || note > 127) return;
    if (sounding[(size_t) note]) sink.performNoteOff (note, time);
    sounding[(size_t) note] = true;
    sink.performNoteOn (note, vel, time);
}

void Performer::noteOff (int note, int64_t time)
{
    if (note < 0 || note > 127 || ! sounding[(size_t) note]) return;
    sounding[(size_t) note] = false;
    sink.performNoteOff (note, time);
}

void Performer::allOff()
{
    queueSize = 0;
    for (int n = 0; n < 128; ++n)
        if (sounding[(size_t) n]) noteOff (n, now);
}

void Performer::setMode (PerformMode m)
{
    if (m == mode) return;
    allOff();
    const auto held = notes;
    notes = {};
    mode = m;
    if (held.size > 0)
        chordChanged (held, velocity);
}

//==============================================================================
void Performer::chordChanged (const NoteList& newNotes, int vel)
{
    const bool wasEmpty = notes.size == 0;
    notes = newNotes;
    velocity = vel;

    if (newNotes.size == 0)
    {
        if (mode == PerformMode::Harp) cancelPendingNoteOns();
        else allOff();
        return;
    }

    switch (mode)
    {
        case PerformMode::Block:
        {
            queueSize = 0;
            for (int n = 0; n < 128; ++n)
                if (sounding[(size_t) n] && ! newNotes.contains (n)) noteOff (n, now);
            for (int i = 0; i < newNotes.size; ++i)
                if (! sounding[(size_t) newNotes[i]]) noteOn (newNotes[i], vel, now);
            return;
        }

        case PerformMode::Strum:
        case PerformMode::Strum2Oct:
        case PerformMode::Slop:
        {
            allOff();
            NoteList seqNotes = newNotes;
            if (mode == PerformMode::Strum2Oct)
                for (int i = 0; i < newNotes.size; ++i) seqNotes.add (newNotes[i] + 12);
            const double gap = strumMs * 0.001 * sr;
            for (int i = 0; i < seqNotes.size; ++i)
            {
                if (mode == PerformMode::Slop)
                {
                    const auto t = now + (int64_t) (random.nextFloat() * slopMs * 0.001 * sr);
                    const int v = juce::jlimit (1, 127, vel + random.nextInt ({ -25, 11 }));
                    schedule (t, true, seqNotes[i], v);
                }
                else
                    schedule (now + (int64_t) (i * gap), true, seqNotes[i], vel);
            }
            return;
        }

        case PerformMode::Harp:
        {
            cancelPendingNoteOns();
            SmallList<12> pcs;
            for (int i = 0; i < newNotes.size; ++i)
                if (! pcs.contains (newNotes[i] % 12)) pcs.add (newNotes[i] % 12);
            pcs.sort();
            const int start = newNotes[0];
            const int total = 3 * pcs.size + 1;
            const double gap = harpMs * 0.001 * sr;
            const auto ring = (int64_t) (0.35 * sr);
            int count = 0;
            for (int octave = start - start % 12; count < total; octave += 12)
            {
                for (int i = 0; i < pcs.size && count < total; ++i)
                {
                    const int n = octave + pcs[i];
                    if (n < start) continue;
                    const auto t = now + (int64_t) (count * gap);
                    schedule (t, true, n, vel);
                    schedule (t + ring, false, n);
                    ++count;
                }
            }
            return;
        }

        case PerformMode::Arp:
        case PerformMode::Arp2Oct:
        case PerformMode::Pattern:
        {
            if (! wasEmpty)
                return; // keeps running on the grid with the new notes
            // A fresh press fires immediately; swallow the next tick if it is too close.
            arpIndex = 0;
            const double len = stepLength();
            const double pos = (now - origin) / len;
            const auto nextTick = (int64_t) std::ceil (pos);
            int64_t stepNumber;
            if ((double) nextTick - pos < 0.5)
            {
                lastTick = nextTick;
                stepNumber = (int64_t) std::llround ((double) nextTick * len / sixteenth);
            }
            else
                stepNumber = (int64_t) (pos * len / sixteenth);
            fireStep (now, len, stepNumber);
            return;
        }

        case PerformMode::NumModes: break;
    }
}

//==============================================================================
double Performer::stepLength() const
{
    return mode == PerformMode::Pattern ? sixteenth : sixteenth * rates[arpRate].sixteenths;
}

void Performer::fireStep (int64_t time, double stepLen, int64_t stepNumber)
{
    if (notes.size == 0) return;
    const auto gateLen = std::max<int64_t> (1, (int64_t) (stepLen * gate));

    if (mode == PerformMode::Pattern)
    {
        const int code = patterns[pattern].steps[((stepNumber % 16) + 16) % 16];
        if (code == R) return;
        const int accent = (stepNumber % 4 == 0) ? velocity : (int) (velocity * 0.8f);
        for (int i = 0; i < notes.size; ++i)
        {
            const bool play = code == ALL || (code == UP && i > 0) || (code >= 0 && i == code % notes.size);
            if (play)
            {
                schedule (time, true, notes[i], accent);
                schedule (time + gateLen, false, notes[i]);
            }
        }
        return;
    }

    NoteList seqNotes = notes;
    if (mode == PerformMode::Arp2Oct)
        for (int i = 0; i < notes.size; ++i) seqNotes.add (notes[i] + 12);
    const int n = seqNotes[arpIndex % seqNotes.size];
    ++arpIndex;
    schedule (time, true, n, velocity);
    schedule (time + gateLen, false, n);
}

void Performer::process (int64_t blockStart, int numSamples, double sixteenthSamples, double gridOrigin)
{
    now = blockStart;
    sixteenth = sixteenthSamples;
    origin = gridOrigin;
    const int64_t end = blockStart + numSamples;

    if (isClocked() && notes.size > 0)
    {
        const double len = stepLength();
        auto tick = (int64_t) std::ceil ((blockStart - origin) / len);
        for (double t = origin + tick * len; t < (double) end; ++tick, t = origin + tick * len)
        {
            if (tick == lastTick) continue;
            lastTick = tick;
            const auto stepNumber = (int64_t) std::llround ((t - origin) / sixteenth);
            fireStep (std::max (blockStart, (int64_t) t), len, stepNumber);
        }
    }

    int consumed = 0;
    while (consumed < queueSize && queue[(size_t) consumed].time < end)
    {
        const auto e = queue[(size_t) consumed++];
        const auto t = std::max (e.time, blockStart);
        if (e.on) noteOn (e.note, e.velocity, t);
        else      noteOff (e.note, t);
    }
    if (consumed > 0)
    {
        for (int i = consumed; i < queueSize; ++i) queue[(size_t) (i - consumed)] = queue[(size_t) i];
        queueSize -= consumed;
    }
}
}
