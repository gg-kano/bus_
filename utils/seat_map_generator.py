"""
Dynamic Bus Seat Map Generator

Generates seat map images with configurable:
- Total seats
- Seats per row (4 = 2-2 layout, 3 = 1-2 layout)
- Seat colors based on status (available/occupied/selected)
"""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
from typing import List, Dict, Literal
from io import BytesIO
import base64

# Colors
COLORS = {
    "available": "#3B82F6",   # Blue
    "occupied": "#EF4444",    # Red
    "selected": "#F97316",    # Orange
}

# Default paths - check Docker path first, then local path
def get_frame_path():
    """Get frame image path, works in both Docker and local environments."""
    # Docker path (mounted at /image)
    docker_path = Path("/image/bus_birdview_frame.png")
    if docker_path.exists():
        return docker_path

    # Local development path
    local_path = Path(__file__).parent.parent / "image" / "bus_birdview_frame.png"
    if local_path.exists():
        return local_path

    # Fallback
    return local_path

FRAME_PATH = get_frame_path()


class SeatMapConfig:
    """Configuration for seat map generation"""

    def __init__(
        self,
        total_seats: int = 36,
        seats_per_row: int = 4,
        layout: Literal["2-2", "1-2", "2-1"] = "2-2",
        seat_width: int = 55,
        seat_height: int = 55,
        seat_radius: int = 8,
        # Area where seats can be placed (relative to frame image)
        seat_area_top: int = 270,
        seat_area_bottom: int = 1245,
        seat_area_left: int = 95,
        seat_area_right: int = 405,
        aisle_width: int = 30,
    ):
        self.total_seats = total_seats
        self.seats_per_row = seats_per_row
        self.layout = layout
        self.seat_width = seat_width
        self.seat_height = seat_height
        self.seat_radius = seat_radius
        self.seat_area_top = seat_area_top
        self.seat_area_bottom = seat_area_bottom
        self.seat_area_left = seat_area_left
        self.seat_area_right = seat_area_right
        self.aisle_width = aisle_width

    @property
    def num_rows(self) -> int:
        """Calculate number of rows needed"""
        import math
        return math.ceil(self.total_seats / self.seats_per_row)

    @property
    def row_height(self) -> float:
        """Calculate height spacing between rows"""
        available_height = self.seat_area_bottom - self.seat_area_top
        return available_height / self.num_rows

    @property
    def left_seats(self) -> int:
        """Number of seats on left side of aisle"""
        if self.layout == "2-2":
            return 2
        elif self.layout == "1-2":
            return 1
        elif self.layout == "2-1":
            return 2
        return 2

    @property
    def right_seats(self) -> int:
        """Number of seats on right side of aisle"""
        if self.layout == "2-2":
            return 2
        elif self.layout == "1-2":
            return 2
        elif self.layout == "2-1":
            return 1
        return 2


def calculate_seat_positions(config: SeatMapConfig) -> Dict[int, tuple]:
    """
    Calculate (x, y) positions for all seats based on config.

    Returns:
        Dict mapping seat_number -> (x, y) top-left corner
    """
    positions = {}
    seat_num = 1

    # Calculate horizontal positions
    total_width = config.seat_area_right - config.seat_area_left
    seat_gap = 8  # Gap between seats in same section

    if config.layout == "1-2":
        # Special layout: 1 seat on left (close to left edge), 2 seats on right
        # Left seat starts at left edge with small padding
        left_padding = 10

        # Right section: 2 seats close together on the right side
        right_section_width = (config.seat_width * 2) + seat_gap
        right_section_start = config.seat_area_right - right_section_width - 10  # 10px padding from right

        for row in range(config.num_rows):
            y = config.seat_area_top + (row * config.row_height) + (config.row_height - config.seat_height) / 2

            # Left side: 1 seat close to left edge
            if seat_num <= config.total_seats:
                x = config.seat_area_left + left_padding
                positions[seat_num] = (int(x), int(y))
                seat_num += 1

            # Right side: 2 seats
            for i in range(2):
                if seat_num > config.total_seats:
                    break
                x = right_section_start + (i * (config.seat_width + seat_gap))
                positions[seat_num] = (int(x), int(y))
                seat_num += 1

    elif config.layout == "2-1":
        # Special layout: 2 seats on left, 1 seat on right (close to right edge)
        right_padding = 10

        # Left section: 2 seats close together on the left side
        left_section_start = config.seat_area_left + 10

        for row in range(config.num_rows):
            y = config.seat_area_top + (row * config.row_height) + (config.row_height - config.seat_height) / 2

            # Left side: 2 seats
            for i in range(2):
                if seat_num > config.total_seats:
                    break
                x = left_section_start + (i * (config.seat_width + seat_gap))
                positions[seat_num] = (int(x), int(y))
                seat_num += 1

            # Right side: 1 seat close to right edge
            if seat_num <= config.total_seats:
                x = config.seat_area_right - config.seat_width - right_padding
                positions[seat_num] = (int(x), int(y))
                seat_num += 1

    else:
        # Default 2-2 layout
        left_section_width = (total_width - config.aisle_width) / 2
        right_section_start = config.seat_area_left + left_section_width + config.aisle_width

        # Calculate seat spacing within each section
        left_seat_spacing = left_section_width / config.left_seats
        right_seat_spacing = left_section_width / config.right_seats

        for row in range(config.num_rows):
            y = config.seat_area_top + (row * config.row_height) + (config.row_height - config.seat_height) / 2

            # Left side seats
            for i in range(config.left_seats):
                if seat_num > config.total_seats:
                    break
                x = config.seat_area_left + (i * left_seat_spacing) + (left_seat_spacing - config.seat_width) / 2
                positions[seat_num] = (int(x), int(y))
                seat_num += 1

            # Right side seats
            for i in range(config.right_seats):
                if seat_num > config.total_seats:
                    break
                x = right_section_start + (i * right_seat_spacing) + (right_seat_spacing - config.seat_width) / 2
                positions[seat_num] = (int(x), int(y))
                seat_num += 1

    return positions


def generate_seat_map(
    occupied_seats: List[int] = None,
    selected_seats: List[int] = None,
    config: SeatMapConfig = None,
    frame_path: str = None,
    output_path: str = None,
) -> Image.Image:
    """
    Generate a seat map image with colored seats.

    Args:
        occupied_seats: List of seat numbers that are occupied (red)
        selected_seats: List of seat numbers that are selected (orange)
        config: SeatMapConfig object with layout settings
        frame_path: Path to bus frame image
        output_path: Optional path to save the generated image

    Returns:
        PIL Image object
    """
    if occupied_seats is None:
        occupied_seats = []
    if selected_seats is None:
        selected_seats = []
    if config is None:
        config = SeatMapConfig()
    if frame_path is None:
        frame_path = FRAME_PATH

    # Load the bus frame
    img = Image.open(frame_path).convert("RGBA")
    draw = ImageDraw.Draw(img)

    # Try to load a font, fallback to default (bigger font for bigger seats)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/freefont/FreeSansBold.ttf", 18)
        except (OSError, IOError):
            font = ImageFont.load_default()

    # Get seat positions
    positions = calculate_seat_positions(config)

    # Draw each seat
    for seat_num, (x, y) in positions.items():
        # Determine seat color
        if seat_num in occupied_seats:
            color = COLORS["occupied"]
        elif seat_num in selected_seats:
            color = COLORS["selected"]
        else:
            color = COLORS["available"]

        # Draw rounded rectangle for seat
        draw.rounded_rectangle(
            [x, y, x + config.seat_width, y + config.seat_height],
            radius=config.seat_radius,
            fill=color,
            outline="#1E3A5F",
            width=2
        )

        # Draw seat number (centered)
        text = str(seat_num)
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        text_x = x + (config.seat_width - text_width) / 2
        text_y = y + (config.seat_height - text_height) / 2
        draw.text((text_x, text_y), text, fill="white", font=font)

    # Save if output path provided
    if output_path:
        img.save(output_path)

    return img


def generate_seat_map_base64(
    occupied_seats: List[int] = None,
    selected_seats: List[int] = None,
    config: SeatMapConfig = None,
    frame_path: str = None,
) -> str:
    """
    Generate seat map and return as base64 string (for web display).

    Returns:
        Base64 encoded PNG image string
    """
    img = generate_seat_map(
        occupied_seats=occupied_seats,
        selected_seats=selected_seats,
        config=config,
        frame_path=frame_path,
    )

    # Convert to base64
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def generate_seat_map_bytes(
    occupied_seats: List[int] = None,
    selected_seats: List[int] = None,
    config: SeatMapConfig = None,
    frame_path: str = None,
) -> BytesIO:
    """
    Generate seat map and return as BytesIO (for Streamlit/web display).

    Returns:
        BytesIO object containing PNG image
    """
    img = generate_seat_map(
        occupied_seats=occupied_seats,
        selected_seats=selected_seats,
        config=config,
        frame_path=frame_path,
    )

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer


def preview_seat_layout(
    total_seats: int,
    seats_per_row: int,
    layout: str,
    frame_path: str = None,
    booked_seats: List[int] = None,
) -> Image.Image:
    """
    Quick preview function for admin panel.
    Shows seats with optional booked seats highlighted.

    Args:
        total_seats: Total number of seats
        seats_per_row: Seats per row (3 or 4)
        layout: "2-2", "1-2", or "2-1"
        frame_path: Path to bus frame image
        booked_seats: List of seat numbers that are booked (shown in red)

    Returns:
        PIL Image object (can be directly used with st.image())
    """
    config = SeatMapConfig(
        total_seats=total_seats,
        seats_per_row=seats_per_row,
        layout=layout,
    )

    return generate_seat_map(
        occupied_seats=booked_seats or [],
        selected_seats=[],
        config=config,
        frame_path=frame_path,
    )


# Quick usage examples
if __name__ == "__main__":
    BASE_DIR = Path(__file__).parent.parent

    # Example 1: 36 seats, 4 per row (2-2 layout)
    config_36 = SeatMapConfig(
        total_seats=36,
        seats_per_row=4,
        layout="2-2"
    )

    # Generate with some occupied and selected seats
    img = generate_seat_map(
        occupied_seats=[2, 5, 6, 11, 15, 20],
        selected_seats=[7, 8],
        config=config_36,
        output_path=str(BASE_DIR / "image" / "seat_map_example.png")
    )
    print("Generated: seat_map_example.png")

    # Example 2: 27 seats, 3 per row (1-2 layout)
    config_27 = SeatMapConfig(
        total_seats=27,
        seats_per_row=3,
        layout="1-2"
    )

    img2 = generate_seat_map(
        occupied_seats=[1, 4, 7, 10],
        config=config_27,
        output_path=str(BASE_DIR / "image" / "seat_map_27_example.png")
    )
    print("Generated: seat_map_27_example.png")
