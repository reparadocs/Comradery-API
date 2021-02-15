import itertools
import re
import unicodedata

import tinycss2
from rcssmin import cssmin

SIMPLE_TOKEN_TYPES = {
    "dimension",
    "hash",
    "ident",
    "literal",
    "number",
    "percentage",
    "string",
    "whitespace",
}


VENDOR_PREFIXES = {
    "-apple-",
    "-khtml-",
    "-moz-",
    "-ms-",
    "-o-",
    "-webkit-",
}
assert all(prefix == prefix.lower() for prefix in VENDOR_PREFIXES)


SAFE_PROPERTIES = {
    "align-content",
    "align-items",
    "align-self",
    "animation",
    "animation-delay",
    "animation-direction",
    "animation-duration",
    "animation-fill-mode",
    "animation-iteration-count",
    "animation-name",
    "animation-play-state",
    "animation-timing-function",
    "appearance",
    "backface-visibility",
    "background",
    "background-attachment",
    "background-blend-mode",
    "background-clip",
    "background-color",
    "background-image",
    "background-origin",
    "background-position",
    "background-position-x",
    "background-position-y",
    "background-repeat",
    "background-size",
    "border",
    "border-bottom",
    "border-bottom-color",
    "border-bottom-left-radius",
    "border-bottom-right-radius",
    "border-bottom-style",
    "border-bottom-width",
    "border-collapse",
    "border-color",
    "border-image",
    "border-image-outset",
    "border-image-repeat",
    "border-image-slice",
    "border-image-source",
    "border-image-width",
    "border-left",
    "border-left-color",
    "border-left-style",
    "border-left-width",
    "border-radius",
    "border-radius-bottomleft",
    "border-radius-bottomright",
    "border-radius-topleft",
    "border-radius-topright",
    "border-right",
    "border-right-color",
    "border-right-style",
    "border-right-width",
    "border-spacing",
    "border-style",
    "border-top",
    "border-top-color",
    "border-top-left-radius",
    "border-top-right-radius",
    "border-top-style",
    "border-top-width",
    "border-width",
    "bottom",
    "box-shadow",
    "box-sizing",
    "caption-side",
    "clear",
    "clip",
    "clip-path",
    "color",
    "content",
    "counter-increment",
    "counter-reset",
    "cue",
    "cue-after",
    "cue-before",
    "cursor",
    "direction",
    "display",
    "elevation",
    "empty-cells",
    "flex",
    "flex-align",
    "flex-basis",
    "flex-direction",
    "flex-flow",
    "flex-grow",
    "flex-item-align",
    "flex-line-pack",
    "flex-order",
    "flex-pack",
    "flex-shrink",
    "flex-wrap",
    "float",
    "font",
    "font-family",
    "font-size",
    "font-style",
    "font-variant",
    "font-weight",
    "grid",
    "grid-area",
    "grid-auto-columns",
    "grid-auto-flow",
    "grid-auto-position",
    "grid-auto-rows",
    "grid-column",
    "grid-column-start",
    "grid-column-end",
    "grid-row",
    "grid-row-start",
    "grid-row-end",
    "grid-template",
    "grid-template-areas",
    "grid-template-rows",
    "grid-template-columns",
    "hanging-punctuation",
    "height",
    "hyphens",
    "image-orientation",
    "image-rendering",
    "image-resolution",
    "justify-content",
    "left",
    "letter-spacing",
    "line-break",
    "line-height",
    "list-style",
    "list-style-image",
    "list-style-position",
    "list-style-type",
    "margin",
    "margin-bottom",
    "margin-left",
    "margin-right",
    "margin-top",
    "max-height",
    "max-width",
    "mask",
    "mask-border",
    "mask-border-mode",
    "mask-border-outset",
    "mask-border-repeat",
    "mask-border-source",
    "mask-border-slice",
    "mask-border-width",
    "mask-clip",
    "mask-composite",
    "mask-image",
    "mask-mode",
    "mask-origin",
    "mask-position",
    "mask-repeat",
    "mask-size",
    "min-height",
    "min-width",
    "mix-blend-mode",
    "opacity",
    "order",
    "orphans",
    "outline",
    "outline-color",
    "outline-offset",
    "outline-style",
    "outline-width",
    "overflow",
    "overflow-wrap",
    "overflow-x",
    "overflow-y",
    "padding",
    "padding-bottom",
    "padding-left",
    "padding-right",
    "padding-top",
    "page-break-after",
    "page-break-before",
    "page-break-inside",
    "pause",
    "pause-after",
    "pause-before",
    "perspective",
    "perspective-origin",
    "pitch",
    "pitch-range",
    "play-during",
    "pointer-events",
    "position",
    "quotes",
    "resize",
    "richness",
    "right",
    "speak",
    "speak-header",
    "speak-numeral",
    "speak-punctuation",
    "speech-rate",
    "stress",
    "table-layout",
    "tab-size",
    "text-align",
    "text-align-last",
    "text-decoration",
    "text-decoration-color",
    "text-decoration-line",
    "text-decoration-skip",
    "text-decoration-style",
    "text-indent",
    "text-justify",
    "text-overflow",
    "text-rendering",
    "text-shadow",
    "text-size-adjust",
    "text-space-collapse",
    "text-transform",
    "text-underline-position",
    "text-wrap",
    "top",
    "transform",
    "transform-origin",
    "transform-style",
    "transition",
    "transition-delay",
    "transition-duration",
    "transition-property",
    "transition-timing-function",
    "unicode-bidi",
    "vertical-align",
    "visibility",
    "voice-family",
    "volume",
    "white-space",
    "widows",
    "width",
    "will-change",
    "word-break",
    "word-spacing",
    "z-index",
}
assert all(property == property.lower() for property in SAFE_PROPERTIES)


SAFE_FUNCTIONS = {
    "calc",
    "circle",
    "counter",
    "counters",
    "cubic-bezier",
    "ellipse",
    "hsl",
    "hsla",
    "lang",
    "line",
    "linear-gradient",
    "matrix",
    "matrix3d",
    "not",
    "nth-child",
    "nth-last-child",
    "nth-last-of-type",
    "nth-of-type",
    "perspective",
    "polygon",
    "polyline",
    "radial-gradient",
    "rect",
    "repeating-linear-gradient",
    "repeating-radial-gradient",
    "rgb",
    "rgba",
    "rotate",
    "rotate3d",
    "rotatex",
    "rotatey",
    "rotatez",
    "scale",
    "scale3d",
    "scalex",
    "scaley",
    "scalez",
    "skewx",
    "skewy",
    "steps",
    "translate",
    "translate3d",
    "translatex",
    "translatey",
    "translatez",
}
assert all(function == function.lower() for function in SAFE_FUNCTIONS)

MAX_SIZE_KIB = 100


def strip_vendor_prefix(identifier):
    for prefix in VENDOR_PREFIXES:
        if identifier.startswith(prefix):
            return identifier[len(prefix) :]
    return identifier


class StylesheetValidator(object):
    def validate_url(self, url_node):
        print("url error")
        return True

    def validate_function(self, function_node):
        function_name = strip_vendor_prefix(function_node.lower_name)

        if function_name not in SAFE_FUNCTIONS:
            print("not safe function")
            return True

        return self.validate_component_values(function_node.arguments)

    def validate_block(self, block):
        return self.validate_component_values(block.content)

    def validate_component_values(self, component_values):
        return self.validate_list(
            component_values,
            {
                # {} blocks are technically part of component values but i don't
                # know of any actual valid uses for them in selectors etc. and they
                # can cause issues with e.g.
                # Safari 5: p[foo=bar{}*{background:green}]{background:red}
                "[] block": self.validate_block,
                "() block": self.validate_block,
                "url": self.validate_url,
                "function": self.validate_function,
            },
            ignored_types=SIMPLE_TOKEN_TYPES,
        )

    def validate_declaration(self, declaration):
        if strip_vendor_prefix(declaration.lower_name) not in SAFE_PROPERTIES:
            print("not safe property")
            return True
        return self.validate_component_values(declaration.value)

    def validate_declaration_list(self, declarations):
        return self.validate_list(
            declarations,
            {
                "at-rule": self.validate_at_rule,
                "declaration": self.validate_declaration,
            },
        )

    def validate_qualified_rule(self, rule):
        prelude_errors = self.validate_component_values(rule.prelude)
        declarations = tinycss2.parse_declaration_list(rule.content)
        declaration_errors = self.validate_declaration_list(declarations)
        if prelude_errors or declaration_errors:
            print("prelude or declaration errors")
            return True
        return False

    def validate_at_rule(self, rule):
        print("at rule")
        return True

    def validate_rule_list(self, rules):
        return self.validate_list(
            rules,
            {
                "qualified-rule": self.validate_qualified_rule,
                "at-rule": self.validate_at_rule,
            },
        )

    def validate_list(self, nodes, validators_by_type, ignored_types=["whitespace"]):
        for node in nodes:
            if node.type == "error":
                print("node error")
                return True
            elif node.type == "literal":
                if node.value == ";":
                    print("semicolon error")
                    return True

            validator = validators_by_type.get(node.type)

            if validator:
                if validator(node):
                    print("validation error")
                    return True
            else:
                if not ignored_types or node.type not in ignored_types:
                    print("node type unknown")
                    return True
        return False

    def check_for_evil_codepoints(self, source_lines):
        for line_number, line_text in enumerate(source_lines, start=1):
            for codepoint in line_text:
                # IE<8: *{color: expression\28 alert\28 1 \29 \29 }
                if codepoint == "\\":
                    return True
                # accept these characters that get classified as control
                elif codepoint in ("\t", "\n", "\r"):
                    continue
                # Safari: *{font-family:'foobar\x03;background:url(evil);';}
                elif unicodedata.category(codepoint).startswith("C"):
                    return True

        return False

    def parse_and_validate(self, stylesheet_source):
        if len(stylesheet_source) > (MAX_SIZE_KIB * 1024):
            return ("", True)

        nodes = tinycss2.parse_stylesheet(stylesheet_source)

        source_lines = stylesheet_source.splitlines()

        backslash_errors = self.check_for_evil_codepoints(source_lines)
        validation_errors = self.validate_rule_list(nodes)
        print(backslash_errors)
        print(validation_errors)
        if backslash_errors or validation_errors:
            return ("", True)
        else:
            serialized = cssmin(tinycss2.serialize(nodes))
            return (serialized.encode("utf-8"), False)


def validate_css(stylesheet):
    """Validate and re-serialize the user submitted stylesheet.

    images is a mapping of subreddit image names to their URLs.  The
    re-serialized stylesheet will have %%name%% tokens replaced with their
    appropriate URLs.

    The return value is a two-tuple of the re-serialized (and minified)
    stylesheet and a list of errors.  If the list is empty, the stylesheet is
    valid.

    """
    validator = StylesheetValidator()
    return validator.parse_and_validate(stylesheet)
