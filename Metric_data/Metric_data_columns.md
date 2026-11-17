**## last activity of the day (late night work)** 

&#x20;1. Email or chat sent outside working hours

day\_of\_week

is\_weekend

shift\_start

shift\_end

total\_msgs\_sent

msgs\_sent\_after\_hours

msgs\_sent\_late\_night

first\_msg\_time

last\_msg\_time

after\_hours\_active\_minutes

after\_hours\_ratio

late\_night\_flag

after\_hours\_ratio\_7d\_avg

consecutive\_after\_hours\_days



**##Number of hours of work in a week** 

1\. Average Session length before any break 

day

is\_weekend

avg\_session\_duration\_mins

max\_session\_duration\_mins

total\_breaks\_count

avg\_break\_duration\_mins

extended\_sessions\_count

Profile 



2\. Longest continuous stretch of work without a break 

day

is\_weekend

longest\_stretch\_duration\_mins

stretch\_start\_hour

post\_stretch\_break\_mins

stretch\_intensity\_pct

stretch\_to\_total\_work\_ratio

Profile





3\. Lunch-hour activity (working through lunch)

day

is\_weekend

lunch\_active\_mins

longest\_lunch\_break\_mins

lunch\_work\_ratio

desk\_dining\_flag

lunch\_skipped\_flag

Profile



4\. Time spent in focused, uninterrupted blocks (shrinking blocks signal trouble)

day

is\_weekend

avg\_focus\_block\_mins

max\_focus\_block\_mins

deep\_work\_blocks\_count

total\_focus\_time\_hours

focus\_fragmentation\_ratio

state





**##Error rate**

1\. Backspace and delete ratio (error rate) 

day\_of\_week

is\_weekend

session\_index\_in\_day

hour\_of\_day

decimal\_hour

total\_keystrokes

char\_keystrokes

backspace\_count

delete\_count

total\_correction\_keys

repeated\_backspace\_bursts

gross\_wpm

net\_wpm

mean\_flight\_time\_ms

flight\_time\_std\_ms

backspace\_ratio

correction\_ratio

error\_correction\_efficiency

pause\_before\_correction\_ms

active\_typing\_ratio

profile





For \[**##Keystroke flight time**  

1\. Typing speed (WPM) and its drift from baseline, both unusually fast and unusually slow

2\. Variability in timing between keys pressed

3\. Burst typing followed by long silences

4\. Key hold duration (dwell time)]



Total columns:

&#x20;keystroke\_count

keystrokes\_per\_second

average\_keystroke\_interval\_seconds

keystroke\_interval\_stdev\_seconds

keystroke\_coefficient\_of\_variation





For \[**##Mouse trajectory jitter** 

1\. Pointer speed and acceleration

2\. Click rate, double-click frequency, rapid repeated clicking

3\. Click force or "hard taps"

4\. Scroll speed and aimless, rapid scrolling

5\. Pointer idle time while an app is open (staring at the screen)]



Total columns: 



timestamp

click\_count

clicks\_per\_second

average\_interval\_seconds

click\_interval\_stdev\_seconds

coefficient\_of\_variation

average\_speed\_px\_s

average\_abs\_accel\_px\_s2

total\_abs\_scroll\_ticks

average\_abs\_scroll\_ticks\_s









