"""
CPS310 - 2026 Fall - Assignment #1
Zombie Simulator

Group Members:
1. Sean Sanpietro

"""

import math
import os
import random
import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor


GROUP_MEMBERS = ["Sean Sanpietro"]

WIDTH = 25
HEIGHT = 10
MAX_HUMANS = WIDTH * HEIGHT

STARTING_HUMANS = 200
STARTING_ZOMBIES = 50
MAX_ROUNDS = 100

HUMAN_REPRODUCTION_CHANCE = 0.01
ZOMBIE_DEATH_CHANCE = 0.01

WORKERS = min(4, max(2, os.cpu_count() or 2))
ROUND_DELAY = 0.5
RESET_DATABASE = True

MINI_MAP_WIDTH = 25
MINI_MAP_HEIGHT = 10


class GameState:
    def __init__(self, round_number, humans, zombies):
        self.round_number = round_number
        self.humans = humans
        self.zombies = zombies


class MemoryStorage:
    def __init__(self):
        self.state = None

    def load(self):
        return self.state

    def save(self, state):
        self.state = state


class DatabaseStorage:
    def __init__(self, file_name):
        self.connection = sqlite3.connect(file_name)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS runtime (round_number INTEGER)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS humans (x INTEGER, y INTEGER)"
        )
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS zombies (x INTEGER, y INTEGER)"
        )
        self.connection.commit()

    def clear(self):
        self.connection.execute("DELETE FROM runtime")
        self.connection.execute("DELETE FROM humans")
        self.connection.execute("DELETE FROM zombies")
        self.connection.commit()

    def load(self):
        round_data = self.connection.execute(
            "SELECT round_number FROM runtime"
        ).fetchone()

        if round_data is None:
            return None

        humans = self.connection.execute("SELECT x, y FROM humans").fetchall()
        zombies = self.connection.execute("SELECT x, y FROM zombies").fetchall()
        return GameState(round_data[0], humans, zombies)

    def save(self, state):
        self.connection.execute("DELETE FROM runtime")
        self.connection.execute("DELETE FROM humans")
        self.connection.execute("DELETE FROM zombies")

        self.connection.execute(
            "INSERT INTO runtime VALUES (?)", (state.round_number,)
        )
        self.connection.executemany("INSERT INTO humans VALUES (?, ?)", state.humans)
        self.connection.executemany("INSERT INTO zombies VALUES (?, ?)", state.zombies)
        self.connection.commit()

    def close(self):
        self.connection.close()


# These functions are outside the class so Windows can run them in processes.
def split_agents(agent_list):
    chunks = []
    chunk_size = max(1, math.ceil(len(agent_list) / WORKERS))

    for index in range(0, len(agent_list), chunk_size):
        chunks.append(agent_list[index:index + chunk_size])

    return chunks


def move_humans_worker(data):
    humans, seed = data
    generator = random.Random(seed)
    moved_humans = []

    for human in humans:
        x = human[0]
        y = human[1]
        direction = generator.randint(1, 4)

        if direction == 1:
            x += 1
        elif direction == 2:
            x -= 1
        elif direction == 3:
            y += 1
        else:
            y -= 1

        x = max(0, min(WIDTH - 1, x))
        y = max(0, min(HEIGHT - 1, y))
        moved_humans.append((x, y))

    return moved_humans


def find_neighbors_worker(data):
    zombies, humans = data
    moved_zombies = []

    for zombie in zombies:
        closest_human = humans[0]
        closest_distance = math.dist(zombie, closest_human)

        for human in humans:
            distance = math.dist(zombie, human)

            if distance < closest_distance:
                closest_distance = distance
                closest_human = human

        x = zombie[0]
        y = zombie[1]

        if x < closest_human[0]:
            x += 1
        elif x > closest_human[0]:
            x -= 1

        if y < closest_human[1]:
            y += 1
        elif y > closest_human[1]:
            y -= 1

        moved_zombies.append((x, y))

    return moved_zombies


def process_events_worker(data):
    humans, zombie_locations, human_locations, seed = data
    generator = random.Random(seed)
    survivors = []
    infected = []
    babies = []

    for human in humans:
        x = human[0]
        y = human[1]

        if (x, y) in zombie_locations:
            infected.append((x, y))
            continue

        survivors.append((x, y))
        nearby_human = False

        for x_change in [-1, 0, 1]:
            for y_change in [-1, 0, 1]:
                if x_change == 0 and y_change == 0:
                    continue

                if (x + x_change, y + y_change) in human_locations:
                    nearby_human = True

        if nearby_human and generator.random() < HUMAN_REPRODUCTION_CHANCE:
            baby_x = x + generator.choice([-1, 0, 1])
            baby_y = y + generator.choice([-1, 0, 1])
            baby_x = max(0, min(WIDTH - 1, baby_x))
            baby_y = max(0, min(HEIGHT - 1, baby_y))
            babies.append((baby_x, baby_y))

    return survivors, infected, babies


def zombie_death_worker(data):
    zombies, seed = data
    generator = random.Random(seed)
    remaining_zombies = []

    for zombie in zombies:
        if generator.random() > ZOMBIE_DEATH_CHANCE:
            remaining_zombies.append(zombie)

    return remaining_zombies


class ZombieSimulation:
    def __init__(self, storage):
        self.storage = storage

    def create_state(self):
        cells = []

        for x in range(WIDTH):
            for y in range(HEIGHT):
                cells.append((x, y))

        random.shuffle(cells)
        humans = cells[:STARTING_HUMANS]
        zombies = []

        for i in range(STARTING_ZOMBIES):
            x = random.randint(0, WIDTH - 1)
            y = random.randint(0, HEIGHT - 1)
            zombies.append((x, y))

        return GameState(0, humans, zombies)

    def run_parallel(self, executor, worker, jobs):
        all_agents = []
        results = executor.map(worker, jobs)

        for group in results:
            all_agents.extend(group)

        return all_agents

    def run(self):
        state = self.storage.load()

        if state is None:
            state = self.create_state()

        with ProcessPoolExecutor(max_workers=WORKERS) as executor:
            while state.round_number < MAX_ROUNDS:
                state.round_number += 1
                round_start = time.perf_counter()

                human_jobs = []
                for chunk in split_agents(state.humans):
                    human_jobs.append((chunk, random.randint(1, 1000000)))
                state.humans = self.run_parallel(
                    executor, move_humans_worker, human_jobs
                )

                neighbor_start = time.perf_counter()
                neighbor_jobs = []
                for chunk in split_agents(state.zombies):
                    neighbor_jobs.append((chunk, state.humans))
                state.zombies = self.run_parallel(
                    executor, find_neighbors_worker, neighbor_jobs
                )
                neighbor_time = time.perf_counter() - neighbor_start

                event_start = time.perf_counter()
                zombie_locations = set(state.zombies)
                human_locations = set(state.humans)
                event_jobs = []

                for chunk in split_agents(state.humans):
                    seed = random.randint(1, 1000000)
                    event_jobs.append((chunk, zombie_locations, human_locations, seed))

                event_results = list(executor.map(process_events_worker, event_jobs))
                state.humans = []
                infected = []
                babies = []

                for result in event_results:
                    survivors, new_zombies, new_humans = result
                    state.humans.extend(survivors)
                    infected.extend(new_zombies)
                    babies.extend(new_humans)

                occupied_locations = set(state.humans)
                occupied_locations.update(state.zombies)

                for baby in babies:
                    if len(state.humans) >= MAX_HUMANS:
                        break

                    if baby not in occupied_locations:
                        state.humans.append(baby)
                        occupied_locations.add(baby)

                state.zombies.extend(infected)

                death_jobs = []
                for chunk in split_agents(state.zombies):
                    death_jobs.append((chunk, random.randint(1, 1000000)))
                state.zombies = self.run_parallel(
                    executor, zombie_death_worker, death_jobs
                )
                event_time = time.perf_counter() - event_start

                database_start = time.perf_counter()
                self.storage.save(state)
                database_time = time.perf_counter() - database_start
                round_time = time.perf_counter() - round_start

                self.display_map(state)
                print(
                    "Round time: %.3fs | Neighbor finding: %.3fs | Events: %.3fs | Database: %.3fs"
                    % (round_time, neighbor_time, event_time, database_time)
                )

                if len(state.humans) == 0:
                    print("All humans have been infected!")
                    print("The zombies win!")
                    return

                if len(state.zombies) == 0:
                    print("There are no zombies left!")
                    print("The humans survive!")
                    return

                time.sleep(ROUND_DELAY)

    def display_map(self, state):
        grid = []

        for y in range(MINI_MAP_HEIGHT):
            row = []
            for x in range(MINI_MAP_WIDTH):
                row.append(".")
            grid.append(row)

        for x, y in state.humans:
            map_x = x * MINI_MAP_WIDTH // WIDTH
            map_y = y * MINI_MAP_HEIGHT // HEIGHT
            grid[map_y][map_x] = "H"

        for x, y in state.zombies:
            map_x = x * MINI_MAP_WIDTH // WIDTH
            map_y = y * MINI_MAP_HEIGHT // HEIGHT
            grid[map_y][map_x] = "Z"

        print("\nROUND", state.round_number)
        for row in grid:
            print("".join(row))
        print("Humans:", len(state.humans), "/", MAX_HUMANS)
        print("Zombies:", len(state.zombies))


def main():
    print("Group members:", ", ".join(GROUP_MEMBERS))
    print("Starting agents:", STARTING_HUMANS + STARTING_ZOMBIES)
    print("Workers:", WORKERS)

    storage = DatabaseStorage("zombie_stage2.db")

    if RESET_DATABASE:
        storage.clear()

    # storage = MemoryStorage()

    game = ZombieSimulation(storage)
    game.run()

    if isinstance(storage, DatabaseStorage):
        storage.close()


if __name__ == "__main__":
    main()
