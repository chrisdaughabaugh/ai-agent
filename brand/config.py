"""
RISE SUPPLY CO. — Brand configuration
Single source of truth for brand identity across all agents.
"""

BRAND = {
    "name":        "RISE SUPPLY CO.",
    "tagline":     "Built for those who refuse to settle.",
    "niche":       "motivational mindset",
    "aesthetic":   "bold dark — black, white, gold",

    "colors": {
        "background":  "#111111",
        "primary":     "#FFFFFF",
        "accent_gold": "#C9A84C",
        "secondary":   "#888888",
    },

    "prices": {
        "t_shirt":  27.99,
        "mug":      16.99,
        "tote_bag": 22.99,
    },

    # Shopify store setup
    "shopify": {
        "collections": [
            {
                "title":       "Best Sellers",
                "description": "Our most popular motivational designs — bold prints for driven people.",
                "sort_order":  "BEST_SELLING",
            },
            {
                "title":       "T-Shirts",
                "description": "Premium motivational t-shirts. Wear your mindset.",
                "sort_order":  "BEST_SELLING",
            },
            {
                "title":       "Mugs",
                "description": "Start every morning with intention. Motivational mugs for driven people.",
                "sort_order":  "BEST_SELLING",
            },
            {
                "title":       "Tote Bags",
                "description": "Carry your goals with you. Bold motivational tote bags.",
                "sort_order":  "BEST_SELLING",
            },
        ],

        "homepage_hero": {
            "heading":    "Built for those who refuse to settle.",
            "subheading": "Bold motivational apparel and accessories for the relentlessly driven.",
            "cta":        "Shop the Collection",
        },

        "seo": {
            "title":       "RISE SUPPLY CO. | Motivational Apparel & Gifts",
            "description": "Premium motivational t-shirts, mugs, and tote bags for driven people. Bold designs that speak to your mindset. Ships fast.",
        },
    },
}
