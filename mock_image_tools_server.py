#!/usr/bin/env python3
"""
Real Image Tools MCP Server

A proper MCP server that generates actual PNG images using PIL.
"""

import asyncio
import base64
import json
import logging
from typing import Dict, List, Any
from io import BytesIO

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from PIL import Image, ImageDraw, ImageFont
import random
import math

logger = logging.getLogger(__name__)

class RealImageGenerator:
    """Generate real PNG images using PIL."""
    
    @staticmethod
    def get_font(size: int = 16):
        """Get a font, with fallbacks."""
        font_paths = [
            "/System/Library/Fonts/Arial.ttf",  # macOS
            "/usr/share/fonts/truetype/arial.ttf",  # Linux
            "/Windows/Fonts/arial.ttf",  # Windows
        ]
        
        for path in font_paths:
            try:
                return ImageFont.truetype(path, size)
            except:
                continue
        
        # Fallback to default
        return ImageFont.load_default()
    
    @staticmethod
    def create_network_diagram(width: int = 500, height: int = 400) -> str:
        """Generate a real network diagram."""
        img = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(img)
        
        # Fonts
        title_font = RealImageGenerator.get_font(20)
        node_font = RealImageGenerator.get_font(12)
        
        # Title
        draw.text((width//2 - 80, 20), "Network Diagram", fill='black', font=title_font)
        
        # Generate network nodes
        nodes = [
            (100, 100, "Gateway"),
            (400, 100, "Router"),
            (100, 200, "Switch A"),
            (400, 200, "Switch B"),
            (250, 300, "Server"),
            (150, 350, "Client 1"),
            (350, 350, "Client 2")
        ]
        
        # Draw connections
        connections = [
            (0, 1), (0, 2), (1, 3), (2, 4), (3, 4),
            (2, 5), (3, 6), (4, 5), (4, 6)
        ]
        
        for start_idx, end_idx in connections:
            x1, y1, _ = nodes[start_idx]
            x2, y2, _ = nodes[end_idx]
            draw.line([x1, y1, x2, y2], fill='#3366CC', width=2)
        
        # Draw nodes
        for x, y, label in nodes:
            # Node circle
            radius = 25
            draw.ellipse([x-radius, y-radius, x+radius, y+radius], 
                        fill='#E6F2FF', outline='#3366CC', width=2)
            
            # Node label
            bbox = draw.textbbox((0, 0), label, font=node_font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            draw.text((x - text_width//2, y - text_height//2), label, 
                     fill='black', font=node_font)
        
        # Add legend
        draw.rectangle([10, height-80, 150, height-10], fill='#F5F5F5', outline='black')
        draw.text((20, height-70), "Network Elements:", fill='black', font=node_font)
        draw.text((20, height-55), "• Nodes: Network devices", fill='black', font=node_font)
        draw.text((20, height-40), "• Lines: Connections", fill='black', font=node_font)
        draw.text((20, height-25), "• Blue: Active links", fill='black', font=node_font)
        
        # Convert to base64
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    @staticmethod
    def create_flowchart_diagram(width: int = 500, height: int = 600) -> str:
        """Generate a real flowchart diagram."""
        img = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(img)
        
        title_font = RealImageGenerator.get_font(20)
        text_font = RealImageGenerator.get_font(12)
        
        # Title
        draw.text((width//2 - 60, 20), "Process Flow", fill='black', font=title_font)
        
        # Flowchart elements
        elements = [
            (250, 80, "oval", "Start", '#90EE90'),
            (250, 150, "rect", "Initialize", '#ADD8E6'),
            (250, 220, "rect", "Process Data", '#ADD8E6'),
            (250, 290, "diamond", "Valid?", '#FFD700'),
            (150, 360, "rect", "Handle Error", '#FFB6C1'),
            (350, 360, "rect", "Save Result", '#ADD8E6'),
            (250, 450, "rect", "Send Response", '#ADD8E6'),
            (250, 520, "oval", "End", '#90EE90')
        ]
        
        # Draw connections
        connections = [
            (0, 1), (1, 2), (2, 3), (3, 4), (3, 5), (4, 6), (5, 6), (6, 7)
        ]
        
        for start_idx, end_idx in connections:
            x1, y1, _, _, _ = elements[start_idx]
            x2, y2, _, _, _ = elements[end_idx]
            
            # Special handling for diamond connections
            if start_idx == 3:  # From decision diamond
                if end_idx == 4:  # To error (left)
                    draw.line([x1-30, y1, x2+40, y2-20], fill='red', width=2)
                    draw.text((x1-60, y1-10), "No", fill='red', font=text_font)
                elif end_idx == 5:  # To save (right)
                    draw.line([x1+30, y1, x2-40, y2-20], fill='green', width=2)
                    draw.text((x1+40, y1-10), "Yes", fill='green', font=text_font)
            else:
                draw.line([x1, y1+20, x2, y2-20], fill='black', width=2)
                # Arrow head
                if y2 > y1:
                    draw.polygon([(x2-5, y2-15), (x2+5, y2-15), (x2, y2-5)], fill='black')
        
        # Draw elements
        for x, y, shape, text, color in elements:
            if shape == "oval":
                draw.ellipse([x-40, y-15, x+40, y+15], fill=color, outline='black', width=2)
            elif shape == "rect":
                draw.rectangle([x-40, y-15, x+40, y+15], fill=color, outline='black', width=2)
            elif shape == "diamond":
                # Draw diamond as polygon
                points = [(x, y-20), (x+35, y), (x, y+20), (x-35, y)]
                draw.polygon(points, fill=color, outline='black')
            
            # Add text
            bbox = draw.textbbox((0, 0), text, font=text_font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            draw.text((x - text_width//2, y - text_height//2), text, 
                     fill='black', font=text_font)
        
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    @staticmethod
    def create_bar_chart(width: int = 500, height: int = 400, data_desc: str = "sales") -> str:
        """Generate a real bar chart."""
        img = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(img)
        
        title_font = RealImageGenerator.get_font(18)
        label_font = RealImageGenerator.get_font(12)
        
        # Title
        title = f"{data_desc.title()} Data Chart"
        draw.text((width//2 - 80, 20), title, fill='black', font=title_font)
        
        # Chart area
        chart_left = 80
        chart_right = width - 40
        chart_top = 80
        chart_bottom = height - 80
        
        # Draw axes
        draw.line([chart_left, chart_bottom, chart_right, chart_bottom], fill='black', width=2)  # X-axis
        draw.line([chart_left, chart_top, chart_left, chart_bottom], fill='black', width=2)  # Y-axis
        
        # Generate sample data
        categories = ["Q1", "Q2", "Q3", "Q4", "Q5"]
        values = [random.randint(20, 100) for _ in categories]
        max_value = max(values)
        
        # Draw bars
        bar_width = (chart_right - chart_left - 60) // len(categories)
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7']
        
        for i, (cat, val) in enumerate(zip(categories, values)):
            x = chart_left + 30 + i * bar_width
            bar_height = int((val / max_value) * (chart_bottom - chart_top - 20))
            y = chart_bottom - bar_height
            
            # Draw bar
            draw.rectangle([x, y, x + bar_width - 10, chart_bottom], 
                          fill=colors[i % len(colors)], outline='black')
            
            # Draw value on top
            draw.text((x + bar_width//2 - 10, y - 20), str(val), 
                     fill='black', font=label_font)
            
            # Draw category label
            draw.text((x + bar_width//2 - 10, chart_bottom + 10), cat, 
                     fill='black', font=label_font)
        
        # Y-axis labels
        for i in range(0, max_value + 1, max_value // 4):
            y = chart_bottom - int((i / max_value) * (chart_bottom - chart_top - 20))
            draw.text((chart_left - 30, y - 5), str(i), fill='black', font=label_font)
            draw.line([chart_left - 5, y, chart_left, y], fill='gray')
        
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    @staticmethod
    def create_pie_chart(width: int = 500, height: int = 400, data_desc: str = "sales") -> str:
        """Generate a real pie chart."""
        img = Image.new('RGB', (width, height), color='white')
        draw = ImageDraw.Draw(img)
        
        title_font = RealImageGenerator.get_font(18)
        label_font = RealImageGenerator.get_font(12)
        
        # Title
        title = f"{data_desc.title()} Distribution"
        bbox = draw.textbbox((0, 0), title, font=title_font)
        title_width = bbox[2] - bbox[0]
        draw.text((width//2 - title_width//2, 20), title, fill='black', font=title_font)
        
        # Pie chart data
        categories = ["Category A", "Category B", "Category C", "Category D", "Category E"]
        values = [random.randint(10, 40) for _ in categories]
        total = sum(values)
        
        # Chart center and radius
        center_x, center_y = width // 2, height // 2 + 20
        radius = min(width, height) // 3
        
        # Colors
        colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEAA7']
        
        # Draw pie slices
        start_angle = 0
        for i, (cat, val) in enumerate(zip(categories, values)):
            angle = (val / total) * 360
            end_angle = start_angle + angle
            
            # Draw slice
            draw.pieslice([center_x - radius, center_y - radius, 
                          center_x + radius, center_y + radius],
                         start_angle, end_angle, fill=colors[i % len(colors)], 
                         outline='black', width=1)
            
            # Add label
            mid_angle = math.radians((start_angle + end_angle) / 2)
            label_x = center_x + (radius + 30) * math.cos(mid_angle)
            label_y = center_y + (radius + 30) * math.sin(mid_angle)
            
            percentage = (val / total) * 100
            label = f"{cat}\n{percentage:.1f}%"
            
            bbox = draw.textbbox((0, 0), label, font=label_font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            draw.text((label_x - text_width//2, label_y - text_height//2), 
                     label, fill='black', font=label_font)
            
            start_angle = end_angle
        
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    @staticmethod
    def create_screenshot_mock(target: str, width: int = 600, height: int = 400) -> str:
        """Generate a realistic screenshot mockup."""
        img = Image.new('RGB', (width, height), color='#F0F0F0')
        draw = ImageDraw.Draw(img)
        
        title_font = RealImageGenerator.get_font(16)
        text_font = RealImageGenerator.get_font(12)
        
        if target == "desktop":
            # Desktop background
            img = Image.new('RGB', (width, height), color='#2E86C1')
            draw = ImageDraw.Draw(img)
            
            # Desktop icons
            for i in range(3):
                for j in range(2):
                    x = 50 + i * 100
                    y = 50 + j * 80
                    # Icon
                    draw.rectangle([x, y, x+40, y+40], fill='white', outline='black')
                    draw.text((x+5, y+45), f"App {i*2+j+1}", fill='white', font=text_font)
            
            # Taskbar
            draw.rectangle([0, height-40, width, height], fill='#1C2833', outline='black')
            draw.text((20, height-30), f"Desktop Screenshot - {target}", fill='white', font=text_font)
            
        elif target == "browser":
            # Browser window
            # Title bar
            draw.rectangle([0, 0, width, 30], fill='#E8E8E8', outline='black')
            draw.text((10, 8), "Web Browser - Example.com", fill='black', font=text_font)
            
            # Address bar
            draw.rectangle([10, 40, width-10, 70], fill='white', outline='gray')
            draw.text((20, 50), "https://example.com", fill='black', font=text_font)
            
            # Content area
            draw.rectangle([10, 80, width-10, height-10], fill='white', outline='gray')
            draw.text((30, 100), "Web Page Content", fill='black', font=title_font)
            draw.text((30, 130), "This is a mock browser screenshot showing", fill='black', font=text_font)
            draw.text((30, 150), "typical web page layout and elements.", fill='black', font=text_font)
            
        else:  # application or terminal
            # Window frame
            draw.rectangle([0, 0, width, height], fill='white', outline='black', width=2)
            # Title bar
            draw.rectangle([0, 0, width, 30], fill='#D5DBDB', outline='black')
            draw.text((10, 8), f"{target.title()} Window", fill='black', font=text_font)
            
            # Content
            if target == "terminal":
                draw.rectangle([10, 40, width-10, height-10], fill='black')
                draw.text((20, 60), "$ ls -la", fill='#00FF00', font=text_font)
                draw.text((20, 80), "total 64", fill='white', font=text_font)
                draw.text((20, 100), "drwxr-xr-x  5 user  staff   160 May 29 12:30 .", fill='white', font=text_font)
                draw.text((20, 120), "drwxr-xr-x  3 user  staff    96 May 29 12:25 ..", fill='white', font=text_font)
                draw.text((20, 140), "-rw-r--r--  1 user  staff  1024 May 29 12:30 file.txt", fill='white', font=text_font)
            else:
                draw.text((30, 60), f"{target.title()} Application", fill='black', font=title_font)
                draw.text((30, 90), "This is a screenshot of the application", fill='black', font=text_font)
                draw.text((30, 110), "showing the main interface elements.", fill='black', font=text_font)
        
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')

class MockImageTools:
    """Tools that generate real images."""
    
    @staticmethod
    async def create_chart(chart_type: str = "bar", data_desc: str = "sales") -> Dict[str, Any]:
        """Generate real chart images."""
        await asyncio.sleep(0.1)  # Simulate processing
        
        if chart_type == "pie":
            image_data = RealImageGenerator.create_pie_chart(data_desc=data_desc)
        else:  # Default to bar chart for all other types
            image_data = RealImageGenerator.create_bar_chart(data_desc=data_desc)
        
        return {
            "success": True,
            "chart_type": chart_type,
            "image": image_data,
            "format": "png",
            "mime_type": "image/png",
            "description": f"Generated {chart_type} chart showing {data_desc} data trends",
            "data_points": 5,
            "width": 500,
            "height": 400
        }
    
    @staticmethod
    async def take_screenshot(target: str = "desktop") -> Dict[str, Any]:
        """Generate realistic screenshot mockups."""
        await asyncio.sleep(0.1)
        
        image_data = RealImageGenerator.create_screenshot_mock(target)
        
        return {
            "success": True,
            "target": target,
            "image": image_data,
            "format": "png",
            "mime_type": "image/png",
            "description": f"Screenshot of {target} showing current interface",
            "resolution": "600x400",
            "timestamp": "2025-05-29T12:50:00Z"
        }
    
    @staticmethod
    async def create_diagram(diagram_type: str = "flowchart") -> Dict[str, Any]:
        """Generate real diagram images."""
        await asyncio.sleep(0.1)
        
        if diagram_type == "network":
            image_data = RealImageGenerator.create_network_diagram()
        else:  # Default to flowchart for all other types
            image_data = RealImageGenerator.create_flowchart_diagram()
        
        return {
            "success": True,
            "diagram_type": diagram_type,
            "image": image_data,
            "format": "png",
            "mime_type": "image/png",
            "description": f"Generated {diagram_type} diagram showing process workflow",
            "elements": ["nodes", "connections", "decision_points"] if diagram_type == "network" else ["start", "process", "decision", "end"],
            "complexity": "medium"
        }

# Create the MCP server
server = Server("real-image-tools")

@server.list_tools()
async def list_tools() -> List[Tool]:
    """List available real image tools."""
    return [
        Tool(
            name="create_chart",
            description="Create real charts and graphs from data",
            inputSchema={
                "type": "object",
                "properties": {
                    "chart_type": {
                        "type": "string",
                        "enum": ["bar", "pie", "line", "scatter", "histogram"],
                        "description": "Type of chart to generate",
                        "default": "bar"
                    },
                    "data_desc": {
                        "type": "string",
                        "description": "Description of the data to visualize",
                        "default": "sales"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="take_screenshot",
            description="Capture mock screenshots of applications and desktop",
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "enum": ["desktop", "application", "browser", "terminal"],
                        "description": "Target to capture",
                        "default": "desktop"
                    }
                },
                "required": []
            }
        ),
        Tool(
            name="create_diagram",
            description="Generate real flowcharts and process diagrams",
            inputSchema={
                "type": "object",
                "properties": {
                    "diagram_type": {
                        "type": "string",
                        "enum": ["flowchart", "network", "process", "organizational", "uml"],
                        "description": "Type of diagram to generate",
                        "default": "flowchart"
                    }
                },
                "required": []
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: Dict[str, Any]) -> List[TextContent]:
    """Handle tool calls."""
    try:
        if name == "create_chart":
            result = await MockImageTools.create_chart(
                chart_type=arguments.get("chart_type", "bar"),
                data_desc=arguments.get("data_desc", "sales")
            )
        elif name == "take_screenshot":
            result = await MockImageTools.take_screenshot(
                target=arguments.get("target", "desktop")
            )
        elif name == "create_diagram":
            result = await MockImageTools.create_diagram(
                diagram_type=arguments.get("diagram_type", "flowchart")
            )
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
        
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
        
    except Exception as e:
        logger.error(f"Error in tool {name}: {e}")
        return [TextContent(type="text", text=f"Error: {str(e)}")]

async def main():
    """Run the MCP server."""
    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options()
            )
    except Exception as e:
        logger.error(f"Server error: {e}")

if __name__ == "__main__":
    asyncio.run(main())