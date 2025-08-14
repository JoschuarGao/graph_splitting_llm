import os
import osmnx as ox
import networkx as nx
from core.config import CACHE_DIR  

# Disable OSMnx console logging
ox.settings.log_console = False


def load_graph(place: str, dist: int = 20000) -> nx.Graph:
    """
    Download or load an OpenStreetMap road network, cache it as a GraphML file,
    and return it as an undirected NetworkX graph.

    Args:
        place (str): The location name or address to search for in OSM.
        dist (int, optional): Search distance (in meters) around the place. Defaults to 20000.

    Returns:
        nx.Graph: An undirected road network graph.
    """
    # Create a safe filename by removing commas and spaces
    safe = place.replace(",", "").replace(" ", "_")
    path = os.path.join(CACHE_DIR, f"{safe}.graphml")

    # If the GraphML file exists in cache, load it
    if os.path.exists(path):
        G = ox.load_graphml(path)
    else:
        # Otherwise, download the map from OSM and save it to cache
        G = ox.graph_from_address(place, dist=dist, network_type="drive")
        ox.save_graphml(G, path)

    # Convert to undirected graph if necessary
    if G.is_directed():
        G = G.to_undirected()

    return G
