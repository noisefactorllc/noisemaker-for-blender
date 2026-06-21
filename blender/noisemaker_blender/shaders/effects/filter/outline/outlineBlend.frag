#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
// Outline blend pass - darken base where edges are detected

void main() {
    vec2 globalCoord = gl_FragCoord.xy + tileOffset;
    ivec2 dimensions = textureSize(inputTex, 0);
    if (dimensions.x == 0 || dimensions.y == 0) {
        fragColor = vec4(0.0);
        return;
    }

    vec2 uv = gl_FragCoord.xy / vec2(dimensions);
    
    vec4 base = nmTex(inputTex, uv);
    vec4 edges = nmTex(edgesTexture, uv);

    // Edge strength from luminance
    float strength = clamp(edges.r, 0.0, 1.0);
    
    // Outline color: black by default, white if inverted
    vec3 outlineColor = invert > 0.5 ? vec3(1.0) : vec3(0.0);
    
    // Apply outline where edges are present
    vec3 out_rgb = mix(base.rgb, outlineColor, strength);
    
    fragColor = vec4(out_rgb, base.a);
}
