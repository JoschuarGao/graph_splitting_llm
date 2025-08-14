import os
import osmnx as ox
import networkx as nx
from core.config import CACHE_DIR

ox.settings.log_console = False

def load_graph(place: str, dist: int = 20000) -> nx.Graph:
    """
    Download/load an OSM road network, cache it as a GraphML file, 
    and return it as an undirected graph.
    """
    safe = place.replace(",", "").replace(" ", "_")
    path = os.path.join(CACHE_DIR, f"{safe}.graphml")
    if os.path.exists(path):
        G = ox.load_graphml(path)
    else:
        G = ox.graph_from_address(place, dist=dist, network_type="drive")
        ox.save_graphml(G, path)
    if G.is_directed():
        G = G.to_undirected()
    return G
