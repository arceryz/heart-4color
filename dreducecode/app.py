import sys
from dataclasses import is_dataclass
from unittest import result
import networkx as nx
import matplotlib.pyplot as plt
from enum import Enum
from copy import deepcopy
from itertools import combinations
from joblib import Parallel, delayed
import timeit
import math

# Global settings
PRINT_CLR_CNT = True
PRINT_RESULTS = False
PRINT_FALSE = True
USE_FAST_COLOUR = False
USE_FAST_SWITCH = False

# Global constants
# 1: red
# 2: blue
# 3: green
# 4: yellow
COLORS = (1, 2, 3, 4)
COLOR_PAIRINGS = (
    ((1, 2), (3, 4)),
    ((1, 3), (2, 4)),
    ((1, 4), (2, 3))
)


class Config:
    identifier = None
    graph = None
    size = None
    ring_size = None
    no_of_colorings = None
    ring = None
    inside = None


# Data structure to organise info about the Kempe-"blocks" in a ring, for a given coloring/pairing
# Note that an instance is constructed externally, kempe_sectors are not automatically generated for example
# Can also be instantiated with data that would not constitute a grouping. is_valid determines whether this is actually
# the case.
class Grouping:
    # Group essentially stored as a list, and the amount of connections to each other group is tracked
    class Group:
        def __init__(self, id: int, grouping_size: int) -> None:
            self.id = id
            self.sectors = []
            self.connection_count = {}
            for i in range(grouping_size):
                if i != self.id:
                    self.connection_count[i] = 0

        def add(self, sector: int):
            self.sectors.append(sector)

        def update_count(self, group: int, action: str):
            if action == "add":
                self.connection_count[group] += 1
            elif action == "remove":
                self.connection_count[group] -= 1
            else:
                raise Exception("No valid action")
            if self.connection_count[group] < 0:
                raise Exception("Negative amount of connections")

    # Grouping is a list of groups, while simultaneously keeping track of the group of every sector for performance
    def __init__(self, kempe_sectors: list, coloring: dict, color_pairing: tuple, size: int) -> None:
        self.size = size  # Amount of groups
        self.sectors = kempe_sectors  # In order of ring => i & i+1%ringsize are neighbouring sectors
        self.coloring = coloring  # Coloring of the ring
        self.color_pairing = color_pairing
        self.groups = []
        for i in range(size):
            self.groups.append(self.Group(i, size))
        self.sectors_to_group = {}  # Dictionary for faster performance
        self.add_sector_to_group(0, 0)  # "First" sector is added to block 0.

    # Returns groups of neighbouring sectors
    # Note:
    # If sectors don't belong to a group yet, then also no group is returned for that neighbour
    # Neighbouring sectors are never in the same group
    def get_neighboring_groups(self, sector: int):
        neighbors = []
        if (sector - 1) % len(self.sectors) in self.sectors_to_group.keys():  # If the sector belongs to a group
            neighbors.append(self.sectors_to_group.get((sector - 1) % len(self.sectors)))  # Get the group of neighbour
        if (sector + 1) % len(self.sectors) in self.sectors_to_group.keys():
            neighbors.append(self.sectors_to_group.get((sector + 1) % len(self.sectors)))
        return neighbors

    # Returns all groups not used by neighbouring sectors
    def get_available_groups(self, sector: int):
        in_use = self.get_neighboring_groups(sector)
        return [i for i in range(self.size) if i not in in_use]

    # Title says it all
    def add_sector_to_group(self, sector: int, group: int):
        self.sectors_to_group[sector] = group  # Tie group to the sector
        self.groups[group].add(sector)  # Add sector to collection of sectors of the group
        # If sector next to it is in a group, then both groups are connected => +1 connection_count
        for n in self.get_neighboring_groups(sector):  # Groups of neighbouring sectors are now connected so:
            self.groups[group].update_count(n, "add")  # Added group has one more connection
            self.groups[n].update_count(group, "add")  # The neighbouring group has one more connection with added group

    # CTRL_Z for add_sector_to_group
    def remove_last_sector_from_group(self):
        sector, group = self.sectors_to_group.popitem()  # Remove "registration of group membership" for sector
        # Idem dito as in add_sector
        for n in self.get_neighboring_groups(sector):  # For the groups of neighbouring sectors
            self.groups[group].update_count(n, "remove")
            self.groups[n].update_count(group, "remove")
        self.groups[group].sectors.remove(sector)

    # Checks the 3 conditions on whether this is actually a grouping / blocks
    def is_valid(self):
        def is_same_type():  # All colors in group must be member of the same color pair
            for group in self.groups:
                if not len(group.sectors) == 0:
                    nodes = []
                    for sector in group.sectors:
                        nodes.extend(self.sectors[sector])
                    if self.coloring[nodes[0]] in self.color_pairing[0]:
                        pair = self.color_pairing[0]
                    else:
                        pair = self.color_pairing[1]
                    for node in nodes:
                        if not self.coloring[node] in pair:
                            return False
            return True

        # Removing (nodes of) ANY group in the ring => all groups are in one connected component of the leftover "ring"
        def has_no_mutual_overlap():
            for removed in self.groups:
                for group in self.groups:
                    if group.id == removed.id:  # We're only  checking the groups we didn't remove
                        continue
                    if len(group.sectors) <= 1:  # Edge case
                        continue
                    reached = [group.sectors[0]]  # Start with the "first" sector"
                    # List all sectors of the group that we can reach without going over removed sector
                    for i in range(group.sectors[0] + 1, group.sectors[-1] + 1):  # In one direction
                        if i in removed.sectors:
                            break
                        if i in group.sectors:
                            reached.append(i)
                    if len(reached) == len(group.sectors):  # If already succeeded, bypass other direction
                        continue
                    for i in range(group.sectors[0] - 1, group.sectors[1] - len(self.sectors) - 1,
                                   -1):  # In other direction
                        if i % len(self.sectors) in removed.sectors:
                            break
                        if i % len(self.sectors) in group.sectors:
                            reached.append(i)
                    if len(reached) != len(group.sectors):  # Implies we couldn't reach all sectors => not connected
                        return False
            return True

        def is_properly_connected():  # If blocks are connected => they are connected at two points
            for group in self.groups:
                for val in group.connection_count.values():
                    if val == 0 or val == 2:
                        next
                    else:
                        return False
            return True

        return is_same_type() and has_no_mutual_overlap() and is_properly_connected()


def import_graphs(fname: str):
    class State(Enum):
        NEW = 1
        VERTEX = 2
        EDGE = 3

    # with open("vier-kleuren.txt", 'r') as f: # For the specific example
    with open("./dreducecode/{0}".format(fname), 'r') as f:
        data = f.readlines()

    graphs = []
    configs = []

    state = State.NEW

    for line in data:
        line = line.strip()
        if state is State.EDGE and line == '':
            cur_config.inside = cur_graph.subgraph(
                filter(lambda v: v > cur_config.ring_size, cur_graph.nodes)
            )
            cur_config.ring = cur_graph.subgraph(
                filter(lambda v: v <= cur_config.ring_size, cur_graph.nodes)
            )

            state = State.NEW
            cur_graph = None
            nr_of_vertices = -1
        elif state is State.NEW:
            cur_graph = nx.Graph()
            graphs.append(cur_graph)

            cur_config = Config()
            cur_config.identifier = int(line.split()[0])
            configs.append(cur_config)

            state = State.VERTEX
        elif state is State.VERTEX:
            config_data = line.split()
            nr_of_vertices = int(config_data[0])
            cur_graph.add_nodes_from(range(nr_of_vertices))

            cur_config.graph = cur_graph
            cur_config.size = int(config_data[0])
            cur_config.ring_size = int(config_data[1])
            cur_config.no_of_colorings = int(config_data[2])

            state = State.EDGE
        elif state is State.EDGE:
            config_data = line.split()
            if line == '0':
                pass
            elif int(config_data[0]) <= nr_of_vertices:
                vertex = int(config_data[0]) - 1
                for i in range(2, 2 + int(config_data[1])):
                    cur_graph.add_edge(vertex, int(config_data[i]) - 1)
            else:
                pass

    return graphs, configs


def find_all_ring_colorings(size: int):
    # Recursive function over all ring nodes: "1" -> "RING_NODES_AMOUNT".
    # Note that the first nodes of the conf are the ring.
    def recurse(graph: nx.classes.graph.Graph, node: int, coloring: dict, ambiguous_colors: list):
        # BASE KAAS (base case)
        # If node number is > ring_size, the node is not in the ring, but in the inside.
        if node >= graph.number_of_nodes():
            # Therefore all nodes in ring are colored: Now check reducibility and return result
            return [coloring.copy()]
        # RECURSIVE KEES
        else:
            result = []

            # Check which colors are not taken by neighbours
            colors_in_use = [coloring[i] for i in list(graph.neighbors(node)) if i in coloring.keys()]
            colors_available = list(filter(lambda c: c not in colors_in_use, COLORS))

            # If there are more than 1 color unused, choosing between them is arbitrary and would result in isomorphism
            # If there is an arbitrary color decision (2 or more colors not used in the entire coloring), split recursive
            # cases for the "new" color, and other available colors.

            if len(ambiguous_colors) > 1:  # If there are multiple unused colors
                for c in ambiguous_colors:  # Ignore all of these in the code below
                    colors_available.remove(c)
                # Now execute the case of picking one of the colours arbitrarily separately
                coloring[node] = ambiguous_colors.pop()     # Pick an unused color (now used, so removed from ambig...)
                result += recurse(graph, node + 1, coloring, ambiguous_colors) # Use it and continue recursion
                ambiguous_colors.append(coloring[node])     # For the other cases it's not used, push it back on

            while len(colors_available) > 0:  # The normal case: go over all possible colors for this node

                while len(coloring) > node:  # Same coloring structure is used, so we have to undo the effect further
                    # down the recursion before we a new possible color
                    coloring.popitem()  # CTRL Z on the coloring, let's try the other possibility
                coloring[node] = colors_available[0]    # Try a color
                colors_available = colors_available[1::]    # Remove color from our to-do list
                result += recurse(graph, node + 1, coloring, ambiguous_colors)     # Append result tuple to long list
            return result

    # Set up
    graph = nx.cycle_graph(size)
    colors_left = [c for c in COLORS]   # ALl colors are not used in the whole coloring. Starting with any is arbitrary
    coloring = {}    # Start with empty coloring

    # Call the recursive function and return results when complete
    return recurse(graph, 0, coloring, colors_left)  #  result temporarily for possible displays


def check_reducible(config: Config, colorings: list, groupings: dict, implyingsets: list = []):
    results = []
    good_colorings = set()
    remaining_colorings = []
    remaining_groupings = {}
    imply0 = []
    total_colorings = len(colorings)
    for i in range(len(colorings)):
        k, _ = get_special_k(config.graph, COLORS, colorings[i], config.ring_size)
        if k is not None and ggd_test_service(config.graph, k):
            isomorphisms = isomorphism_generator(colorings[i].values())
            results.append((isomorphisms[0], True))
            imply0.append(alfacoloring(isomorphisms[0]))
            for isomorph in isomorphisms:
                good_colorings.add(isomorph)
        else:
            remaining_colorings.append(colorings[i])
            remaining_groupings[len(remaining_groupings)] = groupings[i]
    implyingsets.append(sorted(imply0))

    colorings = remaining_colorings
    groupings = remaining_groupings
    count = len(imply0)
    diff = 1 # any nr > 0 to start
    # We expect to find new good colorings each time
    while diff > 0:
        remaining_colorings = []
        remaining_groupings = {}
        new_good_colorings = set()
        implying = []
        for j in range(len(colorings)):
            reducible = False
            for pairing in groupings[j]:
                success = 0
                for grouping in groupings[j][pairing]:
                    if USE_FAST_SWITCH:
                        res = do_color_switching_nocopy(colorings[j], grouping, good_colorings, config)
                    else:
                        res = do_color_switching(colorings[j], grouping, good_colorings, config)
                    if res:
                        success += 1
                    else:
                        break
                if success == len(groupings[j][pairing]):
                    reducible = True
                    isomorphisms = isomorphism_generator(colorings[j].values())
                    results.append((isomorphisms[0], True))
                    implying.append(alfacoloring(isomorphisms[0]))
                    for isomorph in isomorphisms:
                        new_good_colorings.add(isomorph)
                    break
            if not reducible:
                remaining_colorings.append(colorings[j])
                remaining_groupings[len(remaining_groupings)] = groupings[j]
        colorings = remaining_colorings
        groupings = remaining_groupings
        for c in new_good_colorings:
            good_colorings.add(c)
        diff = len(new_good_colorings)
        if len(implying) > 0:
            implyingsets.append(sorted(implying))
            count += len(implying)

    print("d-reducible map total {:d} out of {:d}".format(count, total_colorings))
    for i in range(len(implyingsets)):
        imp = implyingsets[i]
        print("[phi-{:d} nr={:3d}] =".format(i, len(imp)), end=" ")
        for col in imp:
            print(col, end=" ")
        print()
    results.extend([(c.values(), False) for c in remaining_colorings])

    return results


def compute_kempe_sectors(coloring: dict, pairing: tuple):
    sectors = []
    previous = -1
    # As byproduct of other code / way rings are in conf file, consecutive nodes in for loop are neighbours in ring
    for k, v in sorted(coloring.items(), key=lambda t: t[0]):
        if v in pairing[0]:
            if previous == 0:
                sectors[-1].append(k)
            else:
                sectors.append([k])
            previous = 0
        elif v in pairing[1]:
            if previous == 1:
                sectors[-1].append(k)
            else:
                sectors.append([k])
            previous = 1
        else:
            raise Exception("Color not in any pair!")
    # Merge if first and last are actually same
    if ((coloring[sectors[0][0]] in pairing[0] and coloring[sectors[-1][0]] in pairing[0]) or
            (coloring[sectors[0][0]] in pairing[1] and coloring[sectors[-1][0]] in pairing[1])):
        if sectors[0] != sectors[-1]:
            sectors[0] += sectors[-1]
            sectors.pop(-1)

    return sectors


def find_all_sector_groupings(coloring: dict, kempe_sectors: list, color_pairing: tuple):
    def find_all_sector_groupings_recurse(grouping: Grouping, sector: int, groupings: list, groupings_size: int):
        empty_groups = grouping.size - len(set(grouping.sectors_to_group.values()))
        sectors_left = len(grouping.sectors) - sector
        if empty_groups > sectors_left:
            grouping.remove_last_sector_from_group()
            return
        if sector >= len(grouping.sectors):
            if len(set(grouping.sectors_to_group.values())) == grouping.size and grouping.is_valid():
                groupings.append(deepcopy(grouping))
            grouping.remove_last_sector_from_group()
            return
        available = grouping.get_available_groups(sector)
        global_in_use = {g for g in grouping.sectors_to_group.values()}
        global_free = [g for g in range(grouping.size) if g not in global_in_use]
        if len(global_free) == len(available):
            available = available[0:1]
        else:
            for g in global_free[1::]:
                available.remove(g)
        for group in available:
            grouping.add_sector_to_group(sector, group)
            find_all_sector_groupings_recurse(grouping, sector + 1, groupings, groupings_size)
            if groupings_size == len(groupings):
                grouping.remove_last_sector_from_group()
                return
        grouping.remove_last_sector_from_group()

    valid_groupings = []

    # While I haven't looked at a proof for this it seems that:
    # - an uneven amount of kempe sectors will never have a valid grouping
    # - for n kempe sectors where n is even, will only have valid groupings of size n/2 + 1
    # - the amount of valid groupings found is (n choose (n/2 + 1))/(n/2)
    ks_size = len(kempe_sectors)
    groups = ks_size // 2 + 1
    vgsize = math.comb(ks_size, groups) // (ks_size // 2)
    grouping = Grouping(kempe_sectors, coloring, color_pairing, groups)
    find_all_sector_groupings_recurse(grouping, 1, valid_groupings, vgsize)

    if len(valid_groupings) == 0:
        raise Exception("There should be valid groupings")

    return valid_groupings


# Try all possible allowed changes in the coloring, until we find end up with an extendable one
def do_color_switching(coloring: dict, grouping: Grouping, good_colorings: set, config: Config):
    kempe_sectors = grouping.sectors
    color_pairing = grouping.color_pairing
    grouping_combinations = []
    for i in range(1, grouping.size + 1):  # Combinatorics: all possible combinations of allowed color switch actions
        grouping_combinations += list(combinations(grouping.groups, i))

    for combi in grouping_combinations:  # Try every combinations
        new_coloring = coloring.copy()  # Start over again with the original situation
        for group in combi:  # For all groups that are selected to be switched
            nodes = [node for i in group.sectors for node in kempe_sectors[i]]  # List all individual nodes
            if coloring[nodes[0]] in color_pairing[0]:  # Check first node to see colour pairing of the sector/group
                color_pair = color_pairing[0]
            else:
                color_pair = color_pairing[1]
            for node in nodes:  # Now use that color pairing to do switcheroooo for all nodes in group
                color = coloring[node]
                new_coloring[node] = color_pair[(color_pair.index(color) + 1)%2]

        if len(good_colorings) == 0:
            k, _ = get_special_k(config.graph, COLORS, new_coloring, config.ring_size)
            if k is not None and ggd_test_service(config.graph, k):
                return True # Hurray, you are D-reducible
        elif tuple(new_coloring.values()) in good_colorings:
            return True # Hurray, you are D-reducible

    return False # No color switch could make our relationship work, we can no longer keep living like this


# Try all possible allowed changes in the coloring, until we find end up with an extendable one
def do_color_switching_nocopy(coloring: dict, grouping: Grouping, good_colorings: set, config: Config):
    kempe_sectors = grouping.sectors
    color_pairing = grouping.color_pairing
    grouping_combinations = []

    for i in range(1, grouping.size + 1):  # Combinatorics: all possible combinations of allowed color switch actions
        grouping_combinations += list(combinations(grouping.groups, i))

    new_coloring = coloring
    result = False
    for combi_index in range(len(grouping_combinations)):  # Try every combinations
        # Change every group not in the last one so that we end up with the current combination of  colour switches
        for group in grouping_combinations[combi_index]:
            if combi_index == 0 or group not in grouping_combinations[combi_index - 1]:
                nodes = [node for i in group.sectors for node in kempe_sectors[i]]  # List all individual nodes
                if coloring[nodes[0]] in color_pairing[0]:  # Check first node to see colour pairing of the sector/group
                    color_pair = color_pairing[0]
                else:
                    color_pair = color_pairing[1]
                for node in nodes:  # Now use that color pairing to do switcheroooo for all nodes in group
                    color = coloring[node]
                    new_coloring[node] = color_pair[(color_pair.index(color) + 1) % 2]

        if len(good_colorings) == 0:
            k, _ = get_special_k(config.graph, COLORS, new_coloring, config.ring_size)
            if k is not None and ggd_test_service(config.graph, k):
                result = True  # Hurray, you are D-reducible
        elif tuple(new_coloring.values()) in good_colorings:
            result = True  # Hurray, you are D-reducible

        # Change back every group not in the next one (or all if this is the last iteration)
        for group in grouping_combinations[combi_index]:
            if result == True or combi_index == len(grouping_combinations) - 1 or \
                    group not in grouping_combinations[combi_index + 1]:
                nodes = [node for i in group.sectors for node in kempe_sectors[i]]  # List all individual nodes
                if coloring[nodes[0]] in color_pairing[0]:  # Check first node to see colour pairing of the sector/group
                    color_pair = color_pairing[0]
                else:
                    color_pair = color_pairing[1]
                for node in nodes:  # Now use that color pairing to do switcheroooo for all nodes in group
                    color = coloring[node]
                    new_coloring[node] = color_pair[(color_pair.index(color) + 1) % 2]
        if result == True:
            break
    return result  # No color switch could make our relationship work, we can no longer keep living like this

# def do_color_switching_3(config: Config, coloring: dict, kempe_sectors: list, grouping: Grouping, color_pairing: tuple):
#     grouping_combinations = []
#     for i in range(1, grouping.size + 1):  # Combinatorics: all possible combinations of allowed color switch actions
#         grouping_combinations += list(combinations(grouping.groups, i))
#     result = False
#
#     new_coloring = coloring
#     for combi_index in range(len(grouping_combinations)):  # Try every combinations
#
#         # Change every group not in the last one
#         for group in grouping_combinations[combi_index]:
#             if combi_index == 0 or group not in grouping_combinations[combi_index - 1]:
#                 nodes = [node for i in group.sectors for node in kempe_sectors[i]]  # List all individual nodes
#                 if coloring[nodes[0]] in color_pairing[0]:  # Check first node to see colour pairing of the sector/group
#                     color_pair = color_pairing[0]
#                 else:
#                     color_pair = color_pairing[1]
#                 for node in nodes:  # Now use that color pairing to do switcheroooo for all nodes in group
#                     color = coloring[node]
#                     new_coloring[node] = color_pair[(color_pair.index(color) + 1) % 2]
#         k, _ = get_special_k(config.graph, COLORS, new_coloring, len(new_coloring))
#         if k is not None:  # If we found a coloring over the whole graph (w/ inside)
#             if ggd_test_service(config.graph, k):  # Verify that this extendable coloring is valid
#                 result = True  # Hurray, you are D-reducible
#         # Change back every group not in the next one (or all if this is the last iteration)
#         for group in grouping_combinations[combi_index]:
#             if result == True or combi_index == len(grouping_combinations)-1 or\
#                     group not in grouping_combinations[combi_index + 1]:
#                 nodes = [node for i in group.sectors for node in kempe_sectors[i]]  # List all individual nodes
#                 if coloring[nodes[0]] in color_pairing[0]:  # Check first node to see colour pairing of the sector/group
#                     color_pair = color_pairing[0]
#                 else:
#                     color_pair = color_pairing[1]
#                 for node in nodes:  # Now use that color pairing to do switcheroooo for all nodes in group
#                     color = coloring[node]
#                     new_coloring[node] = color_pair[(color_pair.index(color) + 1) % 2]
#         if result == True:
#             return result
#     return False  # No color switch could make our relationship work, we can no longer keep living like this


def get_special_k(graph, colors, color_dic: dict = {}, start_index=0):
    def get_special_k_recur(graph, node, colors: list, coloring: dict, undo_hist: list): # todo rewrite list as int
        # If already colored, return current (successful) coloring
        if node in coloring.keys():
            return coloring

        use_sort = True
        if not use_sort:
            neighbours = list(graph.neighbors(node))
        else:
            neighbours_unsort = list(graph.neighbors(node))
            neighbour_deg = list(graph.degree)
            neighbours = [i for _, i in sorted(zip(neighbour_deg, neighbours_unsort), reverse=True)]
        avail = list(COLORS)

        # Remove colors already taken by neighbours
        for neighneigh in neighbours:
            if neighneigh in coloring.keys():
                if coloring[neighneigh] in avail:
                    avail.remove(coloring[neighneigh])

        for node_color in avail:
            if USE_FAST_COLOUR:
                new_coloring = coloring
                undo_hist.append(node)
            else:
                new_coloring = coloring.copy()

            new_coloring[node] = node_color
            for neighneigh in neighbours:
                # Colour the other neighbours
                new_coloring = get_special_k_recur(graph, neighneigh, colors, new_coloring, undo_hist)
                if new_coloring is None:
                    if USE_FAST_COLOUR:
                        last = None
                        while last != node:
                            last = undo_hist.pop()
                            coloring.pop(last)
                    break
                elif len(graph) == len(new_coloring):
                    break
            if new_coloring is not None:
                return new_coloring
        return None

    # color_dic: Dictionary with a colour keyed by each node
    color_dic = get_special_k_recur(graph, start_index, colors, color_dic.copy(), [])

    # Check if it was successful
    if color_dic is None:
        return None, None

    # Turn it into list for NX.draw
    color_list = [color_dic[i] for i in range(len(color_dic))]
    return color_list, color_dic  # color_list of the colors corresponding to vertices by order, coloring is dictionary


def ggd_test_service(graph, color_list):
    for e in graph.edges:
        if color_list[e[0]] == color_list[e[1]]:
            return False
    return True


def special_k_to_the_ggd(config: Config, i: int):
    print(f"{i + 1}/2822")  # Hardcoded for parallelness
    print(f"ring_size: {config.ring_size}")
    # sys.stdout.flush()
    k, _ = get_special_k(config.graph, COLORS)
    nx.draw(config.graph, node_color=k)
    plt.show()
    if k is None or not ggd_test_service(config.graph, k):
        print(f'ALARM: NOT COLORABLE: {i}')
        nx.draw(config.graph)
        plt.title(f"i={i}")
        plt.show()


def isomorphism_generator(coloring: list):
    color_permutations = ((1, 2), (1, 3), (1, 4), (2, 3), (2, 4), (3, 4),
                          (1, 2, 3), (1, 2, 4), (1, 3, 2), (1, 3, 4), (1, 4, 2), (1, 4, 3),
                          (1, 2, 3, 4), ((1, 2), (3, 4)), ((1, 3), (2, 4)), ((1, 4), (2, 3)))

    isomorphisms = [tuple(coloring)]
    for permutation in color_permutations:
        switched = []
        if type(permutation[0]) == int:
            for c in coloring:
                if c in permutation:
                    switched.append(permutation[(permutation.index(c)+1)%len(permutation)])
                else:
                    switched.append(c)
            isomorphisms.append(tuple(switched))
        else:
            for c in coloring:
                if c in permutation[0]:
                    switched.append(permutation[0][(permutation[0].index(c)+1)%2])
                else:
                    switched.append(permutation[1][(permutation[1].index(c)+1)%2])
            isomorphisms.append(tuple(switched))
    return isomorphisms


# Checks if coloring is isomorphic up to switching colors,
# GIVEN that they color the SAME graph (not an isomorphic graph necessarily)
def coloring_is_isomorphism(coloring1: dict, coloring2: dict):
    # Check same length
    if len(coloring1) != len(coloring2):
        return False

    # Check same amount of colours
    if len(set(coloring1.values())) != len(set(coloring2.values())):
        return False

    # Group the vertices by color
    c1grouped = dict()
    c2grouped = dict()
    for k, v in sorted(coloring1.items()):
        if v in c1grouped:
            c1grouped[v].append(k)
        else:
            c1grouped[v] = [k]
    for k, v in sorted(coloring2.items()):
        if v in c2grouped:
            c2grouped[v].append(k)
        else:
            c2grouped[v] = [k]

    return list(c1grouped.values()) == list(c2grouped.values())


def check_isomorphism_absence(ringsize: int):
    ans = find_all_ring_colorings(ringsize)
    for a in ans:
        for b in ans:
            if a != b:
                print(f"{ans.index(a)} x {ans.index(b)}: {coloring_is_isomorphism(a, b)}")


def draw_config_components(config: Config):
    nx.draw(config.inside)
    plt.figure()
    nx.draw(config.ring)
    plt.figure()
    # Draw entire graph with 4 koloring
    nx.draw(config,
                   node_color=get_special_k(config.graph, COLORS)[0],
                   with_labels=list(config.graph.nodes))
    plt.show()


def timed_reducibility_check(configs, min, max):
    start = timeit.default_timer()
    d_reduce_all(configs, min, max)
    print("Time taken: ", timeit.default_timer() - start)

def color_graphs_all(configs, multi_thread=True):
    if multi_thread:
        Parallel(n_jobs=8)(delayed(special_k_to_the_ggd)(configs[i], i) for i in range(len(configs)))  # Color all configs
    else:
        for i in range(len(configs)): special_k_to_the_ggd(configs[i], i)     # Single thread version

def ring_alfacolorings(n: int):
    allcolorings = find_all_ring_colorings(n)
    alfa = []
    for el in allcolorings:
        alfa.append(alfacoloring(el.values()))
    return sorted(alfa)

def alfacoloring(coloring) -> str:
    colorsleft = [ "a", "b", "c", "d" ]
    mapping = {}

    stringcol = ""
    for x in coloring:
        if x not in mapping:
            mapping[x] = colorsleft.pop(0)
        stringcol += mapping[x]
    
    return stringcol

def table_print_colorings(height: int, alfas: list):
    for i in range(height):
        for j in range(i, len(alfas), height):
            print(alfas[j], end=" ")
            if j+height < len(alfas):
                print("& ", end="")
        print("\\\\")
    pass

def table_print_colorings_color(height: int, alfas: list, implying: list, reducer: list, stride=10):
    colormap = {}
    imply0map = {}
    for col in implying[0]:
        imply0map[col] = 1

    for i in range(len(implying)):
        iset = implying[i]
        for color in iset:
            colormap[color] = "g{:d}".format(i)
    for col in reducer:
        if col in colormap:
            colormap[col] = "rg"
        else:
            colormap[col] = "rb"
    print(colormap.values())
    for i in range(height):
        for j in range(i, len(alfas), height):
            col = alfas[j]
            cellcolor = "iv"
            extra = ""
            if col in colormap:
                cellcolor = colormap[col]
            else:
                symmetries = symmetry_generator_ber(col)
                for sym in symmetries:
                    if sym in colormap:
                        cellcolor = "sf"
                        extra = "\\textcolor{white}" 

            insertcol =  "\\underline{"+col+"}" if col in imply0map else col
            print("\cellcolor{"+cellcolor+"}" + extra + "{"+insertcol+"}", end=" ")
            if j+height < len(alfas):
                print("& ", end="")
        print("\\\\")
        if (i+1) % stride == 0:
            print("\\hline")
    pass

def alfadist(a: str, b: str):
    count = 0
    for i in range(len(a)):
        if a[i] != b[i]:
            count += 1
    return count

def ring_alfaneighbors(n: int):
    alfas = ring_alfacolorings(n)
    pairs = []
    for a in alfas:
        for b in alfas:
            if alfadist(a, b) == 1:
                pairs.append(a + " " + b)
    return pairs
            

# D-reduce all configurations within the range of specified sizes
def d_reduce_all(configs, ring_size_lower=6, ring_size_upper=16):
    results = {}
    configs = sorted(configs, key=lambda c: c.ring_size)    # Sort by ring size, so we can easily recycle ring groupings

    # Constrain parameter to minimum ring size
    if ring_size_lower < 6:
        ring_size_lower = 6
    config_tracker = 0
    # Find the first config with the starting ring_size
    for c in range(len(configs)):
        if configs[c].ring_size == ring_size_lower:
            config_tracker = c
            break

    # Now go over the range of ringsizes that we want to check
    for ring_size in range(ring_size_lower,ring_size_upper+1):
        colorings = find_all_ring_colorings(ring_size)
        groupings = {}

        # Generate all colourings, and corresponding kempe sectors and groupings for each color pairing
        for i in range(len(colorings)):
            groupings[i] = {}
            for pairing in COLOR_PAIRINGS:
                kempe_sectors = compute_kempe_sectors(colorings[i], pairing)
                # 1 or 2 Kempe sectors will not result in a ring coloring which extends to the interior of the graph
                # TODO: Proof?
                if len(kempe_sectors) < 3:
                    continue
                # It seems that if there are an uneven amount of Kempe sectors, a valid grouping cannot be done
                # TODO: Proof
                elif len(kempe_sectors)%2 == 1:
                    continue
                else:
                    groupings[i][pairing] = find_all_sector_groupings(colorings[i], kempe_sectors, pairing)
        # Go over all configs with that ringsize
        for j in range(config_tracker, len(configs)):
            if configs[j].ring_size > ring_size:
                config_tracker = j
                break
            implyingsets = []
            r = check_reducible(configs[j], colorings, groupings, implyingsets)
            results[configs[j].identifier] = r
            results["#{:d}".format(configs[j].identifier)] = implyingsets
    return results

def alfa_to_number(alfa: str):
    numbers = []
    map = { "a": 1, "b": 2, "c": 3, "d":4 }
    for i in range(len(alfa)):
        numbers.append(map[alfa[i]])
    return numbers

def line5_reducer_test(ber: list):
    # input is the implying sets of the bernhard diamond (confg 2).
    colors = [ 1, 2, 3, 4 ]

    valid_bercolors = {}
    for iset in ber:
        for col in iset:
            valid_bercolors[col] = 1
    
    possible_l5_colors = {}

    for i1 in colors:
        for i2 in colors:
            for i3 in colors:
                for i4 in colors:
                    for i5 in colors:
                        coloring = ( i1, i2, i3, i4, i5 )

                        valid = True
                        for i in range(4):
                            if coloring[i] == coloring[i+1]:
                                valid = False
                                break
                        if valid:
                            alfa = alfacoloring(coloring)
                            possible_l5_colors[alfa] = 1

    sortedlist = list(possible_l5_colors.keys())
    sortedlist.sort()
    bercolorings = {}
    for col in sortedlist:
        num = alfa_to_number(col)
        bercol = [ num[2], num[3], num[4], num[3], num[2], num[1], num[0], num[1] ]
        alfaber = alfacoloring(bercol)
        bercolorings[alfaber] = 1

    final = list(bercolorings.keys())
    final.sort()
    print("A total of {:d} bercolorings from reducer".format(len(final)))
    for col in final:
        print(col, "{:s}".format("Extends" if col in valid_bercolors else ""))

def color_permuter(col: str, key: str):
    newstr = ""
    for i in range(len(col)):
        char = key[i]
        index = int(char)
        newstr += col[index]
    return newstr

def symmetry_generator_ber(col: str):
    return [
        color_permuter(col, "43210765"),
        color_permuter(col, "07654321")
    ]

def eye_reducer_test(ber: list):
    ring8 = ring_alfacolorings(8)

    # input is the implying sets of the bernhard diamond (confg 2).
    colors = [ 1, 2, 3, 4 ]


    implycolors = {}
    valid_bercolors = {}
    for i in range(len(ber)):
        iset = ber[i]
        for col in iset:
            valid_bercolors[col] = 1
            implycolors[col] = i
    
    reducer_colors = []

    for y0 in colors:
        for y1 in colors:
            for y2 in colors:
                for y3 in colors:
                    for y4 in colors:
                        for y5 in colors:
                            valid = \
                                y0 != y1 and \
                                y1 != y2 and \
                                y1 != y3 and \
                                y3 != y4 and \
                                y4 != y5 and \
                                y4 != y0 and \
                                y1 != y4  
                            if valid:
                                coloring = (y0,y1,y2,y3,y4,y5)
                                reducer_colors.append(coloring)

    bercolorings = set()
    for num in reducer_colors:
        bercol = [
                num[0], 
                num[1], 
                num[2], 
                num[1], 
                num[3], 
                num[4], 
                num[5], 
                num[4] ]
        alfaber = alfacoloring(bercol)
        bercolorings.add(alfaber)

    final = list(bercolorings)
    final.sort()
    print("A total of {:d} bercolorings from reducer".format(len(final)))
    for i in range(len(final)):
        col = final[i]
        print(i+1, col, "{:s}".format("p{:d}".format(implycolors[col]) if col in implycolors else ""))
    table_print_colorings_color(46, ring_alfacolorings(8), ber, final)

# Doing the stuffs
########################################################################################################################

graphs, configs = import_graphs("my.conf")     # Get configs from file

#table_print_colorings(46, ring_alfacolorings(8))

# print(len(ring_alfacolorings(5)))
# pairs = ring_alfaneighbors(5)
# for p in pairs:
#     print(p)

#print(symmetry_generator_ber("12345678"))
results = d_reduce_all(configs, 6,8)
eye_reducer_test(results["#2"])

#USE_FAST_SWITCH = False
#timed_reducibility_check(configs, 6, 6)
#timed_reducibility_check(configs, 10, 10)
#USE_FAST_SWITCH = True
# timed_reducibility_check(configs, 6, 6)
#timed_reducibility_check(configs, 10, 10)