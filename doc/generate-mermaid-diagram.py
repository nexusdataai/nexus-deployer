"""
Generate Mermaid diagram code for AWS Serverless Web App Architecture
with customizable styling and visual effects
"""

# Color themes
THEMES = {
    "aws": {
        "aws_service": {"fill": "#FF9900", "stroke": "#232F3E", "color": "#232F3E"},
        "external_service": {"fill": "#00C7B7", "stroke": "#232F3E", "color": "#232F3E"},
        "user": {"fill": "#232F3E", "stroke": "#FF9900", "color": "#FFFFFF"},
        "cluster": {"fill": "#F4F4F4", "stroke": "#232F3E"},
    },
    "modern": {
        "aws_service": {"fill": "#667EEA", "stroke": "#5A67D8", "color": "#FFFFFF"},
        "external_service": {"fill": "#48BB78", "stroke": "#38A169", "color": "#FFFFFF"},
        "user": {"fill": "#ED8936", "stroke": "#DD6B20", "color": "#FFFFFF"},
        "cluster": {"fill": "#EDF2F7", "stroke": "#A0AEC0"},
    },
    "dark": {
        "aws_service": {"fill": "#2D3748", "stroke": "#4A5568", "color": "#E2E8F0"},
        "external_service": {"fill": "#1A365D", "stroke": "#2C5282", "color": "#E2E8F0"},
        "user": {"fill": "#742A2A", "stroke": "#9B2C2C", "color": "#FED7D7"},
        "cluster": {"fill": "#1A202C", "stroke": "#2D3748"},
    },
    "vibrant": {
        "aws_service": {"fill": "#F56565", "stroke": "#C53030", "color": "#FFFFFF"},
        "external_service": {"fill": "#9F7AEA", "stroke": "#805AD5", "color": "#FFFFFF"},
        "user": {"fill": "#ED64A6", "stroke": "#D53F8C", "color": "#FFFFFF"},
        "cluster": {"fill": "#FFF5F5", "stroke": "#FC8181"},
    },
    "ocean": {
        "aws_service": {"fill": "#0BC5EA", "stroke": "#00B5D8", "color": "#FFFFFF"},
        "external_service": {"fill": "#4299E1", "stroke": "#3182CE", "color": "#FFFFFF"},
        "user": {"fill": "#2C5282", "stroke": "#2A4365", "color": "#FFFFFF"},
        "cluster": {"fill": "#EBF8FF", "stroke": "#90CDF4"},
    },
}

# Icon/Shape options for nodes
NODE_SHAPES = {
    "default": ("[", "]"),      # Rectangle
    "rounded": ("(", ")"),      # Rounded rectangle
    "stadium": ("([", "])"),    # Stadium shape
    "circle": ("((", "))"),     # Circle
    "asymmetric": (">", "]"),   # Asymmetric shape
    "rhombus": ("{", "}"),      # Diamond/Rhombus
    "hexagon": ("{{", "}}"),    # Hexagon
    "cylinder": ("[(", ")]"),   # Cylinder (good for databases)
    "cloud": ("(((", ")))"),    # Cloud shape
}


def generate_mermaid_diagram(
    theme="aws",
    direction="LR",
    node_shape="default",
    show_icons=True,
    curved_edges=False,
    thick_edges=False,
    add_descriptions=False
):
    """
    Generate Mermaid diagram with customizable options
    
    Args:
        theme: Color theme (aws, modern, dark, vibrant, ocean)
        direction: Graph direction (LR, RL, TB, BT)
        node_shape: Shape for nodes (default, rounded, stadium, circle, etc.)
        show_icons: Add emoji icons to nodes
        curved_edges: Use curved connection lines
        thick_edges: Use thicker connection lines
        add_descriptions: Add descriptive text to connections
    """
    
    # Get theme colors
    colors = THEMES.get(theme, THEMES["aws"])
    
    # Get node shape brackets
    shape_start, shape_end = NODE_SHAPES.get(node_shape, NODE_SHAPES["default"])
    
    # Special shapes for specific node types
    db_shape = NODE_SHAPES["cylinder"]  # Databases get cylinder shape
    user_shape = NODE_SHAPES["rounded"]  # Users get rounded shape
    
    # Icons (emoji)
    icons = {
        "user": "👤 " if show_icons else "",
        "cognito": "🔐 " if show_icons else "",
        "cloudfront": "🌐 " if show_icons else "",
        "s3": "🗄️ " if show_icons else "",
        "api": "🔌 " if show_icons else "",
        "lambda": "⚡ " if show_icons else "",
        "database": "💾 " if show_icons else "",
        "search": "🔍 " if show_icons else "",
        "sns": "📢 " if show_icons else "",
        "map": "🗺️ " if show_icons else "",
        "payment": "💳 " if show_icons else "",
        "cicd": "🔄 " if show_icons else "",
        "github": "📦 " if show_icons else "",
        "monitor": "📊 " if show_icons else "",
    }
    
    # Connection style
    arrow = "-->" if not curved_edges else "-..->"
    thick_arrow = "==>" if thick_edges else arrow
    
    # Build the diagram
    mermaid_code = f"""graph {direction}
    %% AWS Serverless Web App Architecture
    %% Generated with custom styling
    
    %% Define nodes with custom shapes and icons
    User{user_shape[0]}{icons['user']}User{user_shape[1]}
    
    subgraph Identity["🔒 Identity Provider"]
        Cognito{shape_start}{icons['cognito']}Cognito{shape_end}
    end
    
    subgraph WebContent["☁️ Web Content"]
        CloudFront{shape_start}{icons['cloudfront']}CloudFront CDN{shape_end}
    end
    
    subgraph WebsiteHosting["📦 Website Hosting"]
        S3{shape_start}{icons['s3']}S3 Static Assets{shape_end}
    end
    
    subgraph AppLayer["⚙️ App Layer"]
        APIGateway{shape_start}{icons['api']}API Gateway{shape_end}
        Lambda{shape_start}{icons['lambda']}Lambda Functions{shape_end}
    end
    
    subgraph DataLayer["💽 Data Layer"]
        DynamoDB{db_shape[0]}{icons['database']}DynamoDB{db_shape[1]}
    end
    
    subgraph AuxServices["🔧 Auxiliary Services"]
        CloudSearch{shape_start}{icons['search']}CloudSearch{shape_end}
        SNS{shape_start}{icons['sns']}SNS Notifications{shape_end}
    end
    
    subgraph ExternalServices["🌍 External Services"]
        Mapbox{shape_start}{icons['map']}Mapbox Maps{shape_end}
        Stripe{shape_start}{icons['payment']}Stripe Payments{shape_end}
    end
    
    subgraph ManagementStack["🛠️ Management Stack"]
        CICD{shape_start}{icons['cicd']}CI/CD Pipeline{shape_end}
        GitHub{shape_start}{icons['github']}GitHub{shape_end}
        CloudWatch{shape_start}{icons['monitor']}CloudWatch{shape_end}
    end
    
    %% Define connections"""
    
    # Add connections with optional descriptions
    if add_descriptions:
        mermaid_code += f"""
    User {arrow}|"Authenticate"| Cognito
    Cognito {arrow}|"Authorized"| APIGateway
    User {arrow}|"Request"| CloudFront
    CloudFront {arrow}|"Serve"| S3
    APIGateway {thick_arrow}|"Invoke"| Lambda
    Lambda {thick_arrow}|"Query/Write"| DynamoDB
    Lambda {arrow}|"Search"| CloudSearch
    Lambda {arrow}|"Notify"| SNS
    Lambda {arrow}|"Map API"| Mapbox
    Lambda {arrow}|"Payment"| Stripe
    S3 {arrow}|"Origin"| CloudFront
    CICD {arrow}|"Deploy"| S3
    CICD {arrow}|"Build"| GitHub
    GitHub {arrow}|"Monitor"| CloudWatch"""
    else:
        mermaid_code += f"""
    User {arrow} Cognito
    Cognito {arrow} APIGateway
    User {arrow} CloudFront
    CloudFront {arrow} S3
    APIGateway {thick_arrow} Lambda
    Lambda {thick_arrow} DynamoDB
    Lambda {arrow} CloudSearch
    Lambda {arrow} SNS
    Lambda {arrow} Mapbox
    Lambda {arrow} Stripe
    S3 {arrow} CloudFront
    CICD {arrow} S3
    CICD {arrow} GitHub
    GitHub {arrow} CloudWatch"""
    
    # Add styling
    mermaid_code += f"""
    
    %% Styling with {theme} theme
    classDef awsService fill:{colors['aws_service']['fill']},stroke:{colors['aws_service']['stroke']},stroke-width:2px,color:{colors['aws_service']['color']}
    classDef externalService fill:{colors['external_service']['fill']},stroke:{colors['external_service']['stroke']},stroke-width:2px,color:{colors['external_service']['color']}
    classDef userNode fill:{colors['user']['fill']},stroke:{colors['user']['stroke']},stroke-width:3px,color:{colors['user']['color']}
    
    class Cognito,CloudFront,S3,APIGateway,Lambda,DynamoDB,CloudSearch,SNS,CICD,GitHub,CloudWatch awsService
    class Mapbox,Stripe externalService
    class User userNode
    
    %% Additional styling
    style Identity fill:{colors['cluster']['fill']},stroke:{colors['cluster']['stroke']},stroke-width:2px
    style WebContent fill:{colors['cluster']['fill']},stroke:{colors['cluster']['stroke']},stroke-width:2px
    style WebsiteHosting fill:{colors['cluster']['fill']},stroke:{colors['cluster']['stroke']},stroke-width:2px
    style AppLayer fill:{colors['cluster']['fill']},stroke:{colors['cluster']['stroke']},stroke-width:2px
    style DataLayer fill:{colors['cluster']['fill']},stroke:{colors['cluster']['stroke']},stroke-width:2px
    style AuxServices fill:{colors['cluster']['fill']},stroke:{colors['cluster']['stroke']},stroke-width:2px
    style ExternalServices fill:{colors['cluster']['fill']},stroke:{colors['cluster']['stroke']},stroke-width:2px
    style ManagementStack fill:{colors['cluster']['fill']},stroke:{colors['cluster']['stroke']},stroke-width:2px
"""
    
    return mermaid_code


def save_mermaid_to_file(mermaid_code, filename="architecture-diagram.mmd"):
    """Save Mermaid diagram to a file"""
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(mermaid_code)
    
    print(f"✓ Mermaid diagram saved to: {filename}")
    return filename


def print_available_options():
    """Print all available customization options"""
    print("\n" + "="*60)
    print("AVAILABLE CUSTOMIZATION OPTIONS")
    print("="*60)
    print("\n📊 Themes:")
    for theme in THEMES.keys():
        print(f"  - {theme}")
    
    print("\n🔄 Directions:")
    print("  - LR (Left to Right)")
    print("  - RL (Right to Left)")
    print("  - TB (Top to Bottom)")
    print("  - BT (Bottom to Top)")
    
    print("\n🔷 Node Shapes:")
    for shape in NODE_SHAPES.keys():
        print(f"  - {shape}")
    
    print("\n✨ Visual Effects:")
    print("  - show_icons: Add emoji icons")
    print("  - curved_edges: Use curved connection lines")
    print("  - thick_edges: Use thicker lines for main connections")
    print("  - add_descriptions: Add labels to connections")
    print("="*60 + "\n")


if __name__ == "__main__":
    print("🎨 Mermaid Diagram Generator with Custom Styling\n")
    
    # Print available options
    print_available_options()
    
    # Generate multiple versions with different styles
    configs = [
        {
            "name": "architecture-diagram-aws.mmd",
            "theme": "aws",
            "direction": "LR",
            "node_shape": "default",
            "show_icons": True,
            "curved_edges": False,
            "thick_edges": True,
            "add_descriptions": False,
            "description": "AWS Theme (Default)"
        },
        {
            "name": "architecture-diagram-modern.mmd",
            "theme": "modern",
            "direction": "LR",
            "node_shape": "rounded",
            "show_icons": True,
            "curved_edges": True,
            "thick_edges": False,
            "add_descriptions": True,
            "description": "Modern Theme with Descriptions"
        },
        {
            "name": "architecture-diagram-dark.mmd",
            "theme": "dark",
            "direction": "TB",
            "node_shape": "stadium",
            "show_icons": True,
            "curved_edges": False,
            "thick_edges": True,
            "add_descriptions": False,
            "description": "Dark Theme (Top to Bottom)"
        },
        {
            "name": "architecture-diagram-vibrant.mmd",
            "theme": "vibrant",
            "direction": "LR",
            "node_shape": "rounded",
            "show_icons": True,
            "curved_edges": True,
            "thick_edges": True,
            "add_descriptions": True,
            "description": "Vibrant Theme with All Effects"
        },
    ]
    
    print("📝 Generating diagrams with different styles...\n")
    
    for config in configs:
        name = config.pop("name")
        desc = config.pop("description")
        
        print(f"  → {desc}")
        mermaid_code = generate_mermaid_diagram(**config)
        save_mermaid_to_file(mermaid_code, name)
        print()
    
    print("✅ All diagrams generated successfully!")
    print("\n💡 Tip: You can customize further by editing the script")
    print("   and calling generate_mermaid_diagram() with your own parameters.")
