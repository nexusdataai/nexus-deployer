"""
Generate architecture diagrams using the diagrams library
with customizable styling and visual effects
PLUS Mermaid code generation
"""

# Try to import diagrams library (optional for Mermaid generation)
try:
    from diagrams import Cluster, Diagram, Edge
    from diagrams.aws.compute import Lambda
    from diagrams.aws.network import APIGateway, CloudFront
    from diagrams.aws.database import Database
    from diagrams.aws.analytics import Analytics
    from diagrams.aws.security import Cognito
    from diagrams.aws.integration import SNS
    from diagrams.aws.storage import S3
    from diagrams.onprem.client import Users, Client
    from diagrams.onprem.vcs import Github
    from diagrams.onprem.ci import Jenkins
    DIAGRAMS_AVAILABLE = True
except ImportError:
    DIAGRAMS_AVAILABLE = False
    print("⚠️  'diagrams' library not installed - diagram image generation disabled")
    print("   Mermaid code generation will still work!")
    print("   To enable diagram images: pip install diagrams graphviz\n")


# Color themes for diagrams library
DIAGRAM_THEMES = {
    "aws": {
        "graph_attr": {
            "bgcolor": "white",
            "fontname": "Sans-Serif",
            "fontsize": "14",
            "pad": "0.5",
        },
        "node_attr": {
            "fontname": "Sans-Serif",
            "fontsize": "12",
            "style": "filled",
            "fillcolor": "#FF9900",
            "color": "#232F3E",
            "fontcolor": "#232F3E",
        },
        "edge_attr": {
            "color": "#232F3E",
            "penwidth": "2.0",
        },
    },
    "modern": {
        "graph_attr": {
            "bgcolor": "#F7FAFC",
            "fontname": "Helvetica",
            "fontsize": "14",
            "pad": "0.5",
        },
        "node_attr": {
            "fontname": "Helvetica",
            "fontsize": "12",
            "style": "filled,rounded",
            "fillcolor": "#667EEA",
            "color": "#5A67D8",
            "fontcolor": "white",
        },
        "edge_attr": {
            "color": "#5A67D8",
            "penwidth": "2.5",
        },
    },
    "dark": {
        "graph_attr": {
            "bgcolor": "#1A202C",
            "fontname": "Helvetica",
            "fontsize": "14",
            "pad": "0.5",
        },
        "node_attr": {
            "fontname": "Helvetica",
            "fontsize": "12",
            "style": "filled,rounded",
            "fillcolor": "#2D3748",
            "color": "#4A5568",
            "fontcolor": "#E2E8F0",
        },
        "edge_attr": {
            "color": "#E2E8F0",
            "penwidth": "2.0",
        },
    },
    "vibrant": {
        "graph_attr": {
            "bgcolor": "#FFF5F5",
            "fontname": "Arial",
            "fontsize": "14",
            "pad": "0.5",
        },
        "node_attr": {
            "fontname": "Arial",
            "fontsize": "12",
            "style": "filled,rounded",
            "fillcolor": "#F56565",
            "color": "#C53030",
            "fontcolor": "white",
        },
        "edge_attr": {
            "color": "#C53030",
            "penwidth": "3.0",
        },
    },
}

# Color themes for Mermaid
MERMAID_THEMES = {
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
}

# Edge styles
EDGE_STYLES = {
    "default": {"style": "solid"},
    "bold": {"style": "bold", "penwidth": "3.0"},
    "dashed": {"style": "dashed"},
    "dotted": {"style": "dotted"},
    "curved": {"splines": "curved"},
}


def generate_mermaid_code(
    theme="aws",
    direction="LR",
    show_icons=True,
    curved_edges=False,
    thick_edges=False,
    add_descriptions=False
):
    """
    Generate Mermaid diagram code
    
    Args:
        theme: Color theme (aws, modern, dark, vibrant)
        direction: Graph direction (LR, RL, TB, BT)
        show_icons: Add emoji icons to nodes
        curved_edges: Use curved connection lines
        thick_edges: Use thicker connection lines
        add_descriptions: Add labels to connections
    """
    
    # Get theme colors
    colors = MERMAID_THEMES.get(theme, MERMAID_THEMES["aws"])
    
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
    %% Theme: {theme}
    
    %% Define nodes
    User[{icons['user']}User]
    
    subgraph Identity["🔒 Identity Provider"]
        Cognito[{icons['cognito']}Cognito]
    end
    
    subgraph WebContent["☁️ Web Content"]
        CloudFront[{icons['cloudfront']}CloudFront CDN]
    end
    
    subgraph WebsiteHosting["📦 Website Hosting"]
        S3[{icons['s3']}S3 Static Assets]
    end
    
    subgraph AppLayer["⚙️ App Layer"]
        APIGateway[{icons['api']}API Gateway]
        Lambda[{icons['lambda']}Lambda Functions]
    end
    
    subgraph DataLayer["💽 Data Layer"]
        DynamoDB[{icons['database']}DynamoDB]
    end
    
    subgraph AuxServices["🔧 Auxiliary Services"]
        CloudSearch[{icons['search']}CloudSearch]
        SNS[{icons['sns']}SNS Notifications]
    end
    
    subgraph ExternalServices["🌍 External Services"]
        Mapbox[{icons['map']}Mapbox Maps]
        Stripe[{icons['payment']}Stripe Payments]
    end
    
    subgraph ManagementStack["🛠️ Management Stack"]
        CICD[{icons['cicd']}CI/CD Pipeline]
        GitHub[{icons['github']}GitHub]
        CloudWatch[{icons['monitor']}CloudWatch]
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
    
    %% Cluster styling
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
    
    print(f"  ✓ Mermaid code saved to: {filename}")
    return filename


def generate_diagram(
    theme="aws",
    direction="LR",
    edge_style="default",
    show_labels=True,
    output_format="png",
    filename="aws_serverless_web_app_architecture",
    show_diagram=False,
):
    """
    Generate architecture diagram image with customizable styling
    
    Args:
        theme: Color theme (aws, modern, dark, vibrant)
        direction: Graph direction (LR, RL, TB, BT)
        edge_style: Edge style (default, bold, dashed, dotted, curved)
        show_labels: Show labels on edges
        output_format: Output format (png, jpg, svg, pdf)
        filename: Output filename (without extension)
        show_diagram: Open diagram after generation
    """
    
    if not DIAGRAMS_AVAILABLE:
        print("  ⚠️  Skipping diagram image generation (diagrams library not installed)")
        return None
    
    # Get theme attributes
    theme_config = DIAGRAM_THEMES.get(theme, DIAGRAM_THEMES["aws"])
    edge_config = EDGE_STYLES.get(edge_style, EDGE_STYLES["default"])
    
    # Merge edge configurations
    edge_attrs = {**theme_config["edge_attr"], **edge_config}
    
    # Create diagram with custom attributes
    with Diagram(
        "AWS Serverless Web App Architecture",
        show=show_diagram,
        direction=direction,
        outformat=output_format,
        filename=filename,
        graph_attr=theme_config["graph_attr"],
        node_attr=theme_config["node_attr"],
        edge_attr=edge_attrs,
    ):
        user = Users("User")

        with Cluster("Identity Provider"):
            identity = Cognito("Cognito")

        with Cluster("Web Content"):
            cdn = CloudFront("CloudFront")

        with Cluster("Website Hosting"):
            s3 = S3("S3")

        with Cluster("App Layer"):
            api_gw = APIGateway("API Gateway")
            lambda_func = Lambda("Lambda")

        with Cluster("Data Layer"):
            db = Database("DynamoDB")

        with Cluster("Auxiliary Services"):
            search = Analytics("CloudSearch")
            sns = SNS("SNS")

        with Cluster("External Services"):
            mapbox = Client("Mapbox")
            stripe = Client("Stripe")

        with Cluster("Management Stack"):
            codepipeline = Jenkins("CI/CD")
            github = Github("GitHub")
            monitoring = Analytics("CloudWatch")

        # Define connections with optional labels
        if show_labels:
            user >> Edge(label="authenticate") >> identity
            identity >> Edge(label="authorized") >> api_gw
            user >> Edge(label="request") >> cdn
            cdn >> Edge(label="serve") >> s3
            api_gw >> Edge(label="invoke", color="#FF6B6B") >> lambda_func
            lambda_func >> Edge(label="query", color="#FF6B6B") >> db
            lambda_func >> Edge(label="search") >> search
            lambda_func >> Edge(label="notify") >> sns
            lambda_func >> Edge(label="map API") >> mapbox
            lambda_func >> Edge(label="payment") >> stripe
            s3 >> Edge(label="origin") >> cdn
            s3 << Edge(label="deploy") << codepipeline
            codepipeline >> Edge(label="build") >> github
            github >> Edge(label="monitor") >> monitoring
        else:
            user >> identity >> api_gw
            user >> cdn >> s3
            api_gw >> lambda_func >> db
            lambda_func >> [search, sns]
            lambda_func >> [mapbox, stripe]
            s3 >> cdn
            s3 << codepipeline
            codepipeline >> github >> monitoring

    print(f"  ✓ Diagram image saved: {filename}.{output_format}")
    return f"{filename}.{output_format}"


def generate_all_outputs(output_type="both"):
    """
    Generate diagrams in multiple formats
    
    Args:
        output_type: "diagrams", "mermaid", or "both"
    """
    print("\n" + "="*60)
    print("GENERATING ARCHITECTURE DIAGRAMS")
    print("="*60 + "\n")
    
    configs = [
        {
            "theme": "aws",
            "direction": "LR",
            "description": "AWS Theme"
        },
        {
            "theme": "modern",
            "direction": "LR",
            "description": "Modern Theme"
        },
        {
            "theme": "dark",
            "direction": "TB",
            "description": "Dark Theme (Top to Bottom)"
        },
        {
            "theme": "vibrant",
            "direction": "LR",
            "description": "Vibrant Theme"
        },
    ]
    
    generated_files = []
    
    for config in configs:
        theme = config["theme"]
        direction = config["direction"]
        desc = config["description"]
        
        print(f"📊 {desc}")
        print("-" * 60)
        
        try:
            # Generate diagram image
            if output_type in ["diagrams", "both"]:
                filename = generate_diagram(
                    theme=theme,
                    direction=direction,
                    edge_style="bold",
                    show_labels=True,
                    output_format="png",
                    filename=f"architecture_{theme}_theme",
                    show_diagram=False
                )
                generated_files.append(filename)
            
            # Generate Mermaid code
            if output_type in ["mermaid", "both"]:
                mermaid_code = generate_mermaid_code(
                    theme=theme,
                    direction=direction,
                    show_icons=True,
                    curved_edges=(theme == "modern"),
                    thick_edges=True,
                    add_descriptions=(theme in ["modern", "vibrant"])
                )
                mermaid_file = save_mermaid_to_file(
                    mermaid_code,
                    f"architecture_{theme}_theme.mmd"
                )
                generated_files.append(mermaid_file)
            
            print()
            
        except Exception as e:
            print(f"  ❌ Error: {e}\n")
    
    print("="*60)
    print(f"✅ Generated {len(generated_files)} files successfully!")
    print("="*60)
    
    return generated_files


def print_usage():
    """Print usage instructions"""
    print("\n" + "="*60)
    print("CUSTOMIZATION OPTIONS")
    print("="*60)
    print("\n📊 Available Themes:")
    for theme in DIAGRAM_THEMES.keys():
        print(f"  - {theme}")
    
    print("\n🔄 Directions:")
    print("  - LR (Left to Right)")
    print("  - RL (Right to Left)")
    print("  - TB (Top to Bottom)")
    print("  - BT (Bottom to Top)")
    
    print("\n🔗 Edge Styles (for diagram images):")
    for style in EDGE_STYLES.keys():
        print(f"  - {style}")
    
    print("\n📄 Output Formats:")
    print("  Diagram Images: png, jpg, svg, pdf")
    print("  Mermaid Code: .mmd files")
    
    print("\n💡 Usage Examples:")
    print("  # Generate both images and Mermaid code:")
    print('  generate_all_outputs(output_type="both")')
    print("\n  # Generate only Mermaid code:")
    print('  generate_all_outputs(output_type="mermaid")')
    print("\n  # Generate only diagram images:")
    print('  generate_all_outputs(output_type="diagrams")')
    
    print("\n⚠️  Note: Diagram images require Graphviz")
    print("  Mermaid code generation works without Graphviz!")
    print("="*60 + "\n")


if __name__ == "__main__":
    print("🎨 Architecture Diagram Generator")
    print("   Supports: Diagram Images + Mermaid Code\n")
    
    # Print usage information
    print_usage()
    
    # Generate all outputs (both diagrams and mermaid)
    try:
        generate_all_outputs(output_type="both")
        
        print("\n💡 Tip: Edit the script to customize individual outputs")
        print("   Change output_type to 'mermaid' if Graphviz is not installed.")
        
    except Exception as e:
        print(f"\n❌ Error generating diagram images: {e}")
        print("\n🔄 Trying Mermaid code generation only...")
        
        try:
            generate_all_outputs(output_type="mermaid")
            print("\n✅ Mermaid code generated successfully!")
            print("   (Diagram images skipped - install Graphviz to enable)")
        except Exception as e2:
            print(f"\n❌ Error: {e2}")
