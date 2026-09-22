## A good tool should be a *Pleasure To Use*.

* This file is a collection of suggestions aimed at making Kodacad a *Pleasure To Use*, mostly by improving workflow on *typical* projects.
* Tracks outstanding issues and future development ideas.
* Both developer and user contributions are welcome.

---

## Deferred (Not easily implemented)

* View Cube is unresponsive when other operations are in use
    * Claude: Annoying but cosmetic, and it touches the selection-mode plumbing that has historically been the riskiest code in the app to poke.
    * Workaround: Just middle click to exit the current operation and use the view cube

* Native save / load format
    * Claude:  Blocked, not hard: native `.xbf` save. Session 49 confirmed the OCP binding bug (CadQuery/OCP#182: `Open` returns an empty document while reporting success). No amount of effort on our side fixes that; the move is to re-run our existing smoke test whenever OCP ships a new version.
        * 9/20/26 -- Noticed that cadquery-ocp8.0.1.0.0 was recently released, so I decided to give it a try to see if the save/load failure issue has been resolved. Unfortunately, the answer turned out to be 'No'. Not only is this issue not fixed, the 'upgrade' causes some other problems:
            * Recent (session 106) switch to using MMB for navigation is not supported.
            * Upgrading to this new version requires import statements to be extensively revised.
            * For both of the above reasons, I decided to stay with the previous known-good state and wait for OCP to mature a bit more before "upgrading".
            
            * In the meantime, continue to use the workaround: Just save session (in .STEP format) and reload as next session. Workplanes are not saved.
