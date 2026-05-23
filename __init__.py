"""
Queuechella Festival Simulation Package
========================================
A discrete-event simulation (DES) of the Queuechella music festival.

Modules:
    config          - All constants and configurable parameters
    distributions   - Sampling algorithms (Box-Muller, Inverse Transform,
                      Composition, Accept-Reject)
    entities        - Visitor entity classes (FriendsGroup, Couple, Single)
    stations        - Station and stage classes
    events          - Event type definitions
    engine          - Core DES engine (priority-queue driven)
    sim_stats       - Metrics collection and analysis
    alternatives    - Alternative scenario configurations
"""
