---
id: brand_guidelines_v1
domain: Design System
display_name: Brand Guidelines Stylist
output_types:
- brand_guidelines
version: 1.0.0
role: post_processor
description: Applies brand colors and typography standards to presentation and document
  artifacts. Use when output needs to follow defined visual identity guidelines.
use_when: users request brand-compliant styling, visual consistency, or company-standard
  formatting
tools:
- retrieve_context
- qa_validator
- style_enforcer
workflow_steps:
- Capture target artifact type and styling scope
- Apply brand colors and typography hierarchy
- Review contrast, readability, and consistency
- Finalize brand-compliant output
feedback_loop:
- Apply styling
- Run consistency checks
- Fix contrast/consistency issues
- Finalize
freedom_level: low
quality_thresholds:
  brand_guidelines: 0.9
acceptance_checks:
- Brand colors and typography are applied consistently
- Text contrast and readability are preserved
- Heading/body style hierarchy is clear
- Output reflects requested brand identity
default_representation: markdown
companion_files: []
source_url: https://github.com/anthropics/skills/tree/main/skills/brand-guidelines
sample_instruction: Restyle an existing executive summary and slide content to match
  approved brand colors and typography rules.
custom: false
---

# Anthropic Brand Styling

## Overview

To access Anthropic's official brand identity and style resources, use this skill.

**Keywords**: branding, corporate identity, visual identity, post-processing, styling, brand colors, typography, Anthropic brand, visual formatting, visual design

## Brand Guidelines

### Colors

**Main Colors:**

- Dark: `#141413` - Primary text and dark backgrounds
- Light: `#faf9f5` - Light backgrounds and text on dark
- Mid Gray: `#b0aea5` - Secondary elements
- Light Gray: `#e8e6dc` - Subtle backgrounds

**Accent Colors:**

- Orange: `#d97757` - Primary accent
- Blue: `#6a9bcc` - Secondary accent
- Green: `#788c5d` - Tertiary accent

### Typography

- **Headings**: Poppins (with Arial fallback)
- **Body Text**: Lora (with Georgia fallback)
- **Note**: Fonts should be pre-installed in your environment for best results

## Features

### Smart Font Application

- Applies Poppins font to headings (24pt and larger)
- Applies Lora font to body text
- Automatically falls back to Arial/Georgia if custom fonts unavailable
- Preserves readability across all systems

### Text Styling

- Headings (24pt+): Poppins font
- Body text: Lora font
- Smart color selection based on background
- Preserves text hierarchy and formatting

### Shape and Accent Colors

- Non-text shapes use accent colors
- Cycles through orange, blue, and green accents
- Maintains visual interest while staying on-brand

## Technical Details

### Font Management

- Uses system-installed Poppins and Lora fonts when available
- Provides automatic fallback to Arial (headings) and Georgia (body)
- No font installation required - works with existing system fonts
- For best results, pre-install Poppins and Lora fonts in your environment

### Color Application

- Uses RGB color values for precise brand matching
- Applied via python-pptx's RGBColor class
- Maintains color fidelity across different systems
