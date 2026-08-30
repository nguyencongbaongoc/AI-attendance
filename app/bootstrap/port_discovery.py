"""
Dynamic Port Discovery for AI Attendance System.

Provides robust port allocation in five-digit ranges:
- Backend: 10000-19999
- Frontend: 20000-29999
"""

from __future__ import annotations

import socket
import random
from typing import Optional, Tuple, List
from dataclasses import dataclass


@dataclass
class PortRange:
    """Defines a port range for allocation."""
    start: int
    end: int
    name: str


# Predefined port ranges
BACKEND_PORT_RANGE = PortRange(10000, 19999, "backend")
FRONTEND_PORT_RANGE = PortRange(20000, 29999, "frontend")


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """
    Check if a port is available for binding.
    
    Args:
        port: Port number to check
        host: Host address to check (default: localhost)
        
    Returns:
        True if port is available, False otherwise
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            result = sock.connect_ex((host, port))
            return result != 0
    except OSError:
        return False


def find_available_port(
    port_range: PortRange,
    preferred_port: Optional[int] = None,
    host: str = "127.0.0.1",
    max_attempts: int = 100
) -> int:
    """
    Find an available port within the specified range.
    
    Args:
        port_range: PortRange to search within
        preferred_port: Preferred port to try first (if within range)
        host: Host address to check
        max_attempts: Maximum number of ports to try
        
    Returns:
        Available port number
        
    Raises:
        RuntimeError: If no available port found after max_attempts
    """
    # Try preferred port first if specified and within range
    if preferred_port is not None and port_range.start <= preferred_port <= port_range.end:
        if is_port_available(preferred_port, host):
            return preferred_port
    
    # Generate a deterministic but randomized search order
    # Start from a random offset within the range for better distribution
    range_size = port_range.end - port_range.start + 1
    start_offset = random.randint(0, range_size - 1)
    
    attempts = 0
    for i in range(range_size):
        if attempts >= max_attempts:
            break
            
        port = port_range.start + ((start_offset + i) % range_size)
        
        # Skip preferred port since we already tried it
        if port == preferred_port:
            continue
            
        if is_port_available(port, host):
            return port
        attempts += 1
    
    # Fallback: sequential search from start
    for port in range(port_range.start, port_range.end + 1):
        if port == preferred_port:
            continue
        if is_port_available(port, host):
            return port
    
    raise RuntimeError(
        f"No available port found in {port_range.name} range "
        f"({port_range.start}-{port_range.end}) after {max_attempts} attempts"
    )


def find_backend_port(
    preferred_port: Optional[int] = None,
    host: str = "127.0.0.1"
) -> int:
    """
    Find an available backend port (10000-19999).
    
    Args:
        preferred_port: Preferred port (default: 8000 if in range, else None)
        host: Host address to check
        
    Returns:
        Available backend port
    """
    # Default preferred backend port is 8000, but it's not in our range
    # So we use None and let the algorithm pick the first available
    return find_available_port(BACKEND_PORT_RANGE, preferred_port, host)


def find_frontend_port(
    preferred_port: Optional[int] = None,
    host: str = "127.0.0.1"
) -> int:
    """
    Find an available frontend port (20000-29999).
    
    Args:
        preferred_port: Preferred port (default: 8443 if in range, else None)
        host: Host address to check
        
    Returns:
        Available frontend port
    """
    return find_available_port(FRONTEND_PORT_RANGE, preferred_port, host)


def find_coordinated_ports(
    backend_preferred: Optional[int] = None,
    frontend_preferred: Optional[int] = None,
    host: str = "127.0.0.1"
) -> Tuple[int, int]:
    """
    Find coordinated backend and frontend ports that don't conflict.
    
    Args:
        backend_preferred: Preferred backend port
        frontend_preferred: Preferred frontend port
        host: Host address to check
        
    Returns:
        Tuple of (backend_port, frontend_port)
    """
    backend_port = find_backend_port(backend_preferred, host)
    frontend_port = find_frontend_port(frontend_preferred, host)
    
    # Ensure they're different (should always be true with separate ranges)
    if backend_port == frontend_port:
        # This shouldn't happen with separate ranges, but just in case
        frontend_port = find_frontend_port(None, host)
        if frontend_port == backend_port:
            raise RuntimeError("Could not find non-conflicting ports")
    
    return backend_port, frontend_port


def get_port_info(port: int) -> dict:
    """
    Get information about a port.
    
    Args:
        port: Port number
        
    Returns:
        Dictionary with port information
    """
    info = {
        "port": port,
        "available": is_port_available(port),
    }
    
    if BACKEND_PORT_RANGE.start <= port <= BACKEND_PORT_RANGE.end:
        info["service"] = "backend"
        info["range"] = f"{BACKEND_PORT_RANGE.start}-{BACKEND_PORT_RANGE.end}"
    elif FRONTEND_PORT_RANGE.start <= port <= FRONTEND_PORT_RANGE.end:
        info["service"] = "frontend"
        info["range"] = f"{FRONTEND_PORT_RANGE.start}-{FRONTEND_PORT_RANGE.end}"
    else:
        info["service"] = "unknown"
        info["range"] = "N/A"
    
    return info


def scan_port_range(port_range: PortRange, host: str = "127.0.0.1") -> List[dict]:
    """
    Scan a port range and return availability info for all ports.
    
    Args:
        port_range: PortRange to scan
        host: Host address to check
        
    Returns:
        List of port info dictionaries
    """
    results = []
    for port in range(port_range.start, port_range.end + 1):
        results.append(get_port_info(port))
    return results