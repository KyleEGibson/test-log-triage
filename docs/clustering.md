# Why clusters are exact signatures

## Fuzzy merging went wrong
My first version merged signatures by similarity (TF-IDF, cosine distance, agglomerative clustering at 0.45). On the real JUnit results from the [EOS-100 test station](https://github.com/KyleEGibson/eo-sensor-test-station) it put three different failures in one cluster:

```
AssertionError: BIT result = <NUM> is outside limits <NUM> .. <NUM>
AssertionError: maximum temperature = <NUM> C is outside limits <NUM> .. <NUM>
AssertionError: bus voltage (min of <NUM>) = <NUM> V is outside limits <NUM> .. <NUM>
```

That's a BIT failure, a cooler drift and a voltage sag. They share so much text ("AssertionError ... is outside limits <NUM> .. <NUM>") that the part that's different barely moves the vector.

On the real data the closest two signatures were 0.32 apart, and every distinct signature was actually a different cause, so any threshold loose enough to merge something merged something wrong.

## What I changed
- Clusters are exact signatures after masking. `normalize.py` does the generalizing (numbers, IPs, ports, hex, hashes, UUIDs, timestamps, paths, line numbers, unit IDs).
- Clusters closer than 0.5 get listed as "possibly related" in the report instead of merged.
- Fuzzy merging is still there behind `--merge-threshold`.

Merging two causes hides one of them and a bug doesn't get fixed. Splitting one cause into two clusters just costs the reader a second look, so I'd rather err that way.

## Measurements
`triage eval`, on 400 labeled synthetic failures from 13 root causes:

| Setting | Clusters (true) | ARI | Homogeneity | Completeness | Category accuracy |
|---|---:|---:|---:|---:|---:|
| exact signatures | 13 (13) | 1.000 | 1.000 | 1.000 | 100.0% |
| merge < 0.30 | 13 (13) | 1.000 | 1.000 | 1.000 | 100.0% |
| merge < 0.40 | 12 (13) | 0.885 | 0.943 | 1.000 | 100.0% |
| merge < 0.60 | 11 (13) | 0.849 | 0.909 | 1.000 | 100.0% |

Homogeneity drops as the threshold goes up (causes getting mixed). Completeness was already 1.0, so merging didn't fix any splits, it only added errors.

The 1.0 scores should be taken with a grain of salt since I wrote both the corpus and the masking rules. The better check is the real data: 25 failures from 5 fault-injection runs became 9 clusters, and I went through each one by hand to confirm it was a separate cause.

## Known limitations
- Variable words the rules don't know about split a cause. For example, `db-east` vs `db-west` in an otherwise identical message gives two clusters. That's the cheap kind of error, and the "possibly related" hint usually points it out.
- Known issues match on the message, so an old symptom can have a new cause. In the samples, the slew-time failure from the comm-drop run matches DEF-0041 (slow gimbal motor lot), but the real cause was retry latency on a bad link. The "Seen in" line in the report (which run it came from) is the clue there.
- Different causes with the exact same message can't be told apart from text. The BIT failure appears in three runs (gimbal stall, voltage sag, dead pixels) because the sensor reports one bitmask. Its "Seen in" list covers all three runs, which hints at more than one cause.
