#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
void main() {
    vec2 uv = gl_FragCoord.xy / resolution;
    vec4 inputCol = nmTex(inputTex, uv);
    vec4 grid = nmTex(gridTex, uv);
    
    // Blend grid structure over input
    // Grid alpha indicates structure presence
    float gridStrength = clamp(grid.a, 0.0, 1.0);
    vec3 gridColor = grid.rgb;
    float matteAlpha = matteOpacity;
    
    // Mix: where grid exists, show grid color; otherwise show input (premultiplied by matte)
    vec3 color = mix(inputCol.rgb * matteAlpha, gridColor, gridStrength);
    
    // Alpha: where grid exists, full opacity; elsewhere, matte opacity
    float alpha = max(gridStrength, matteAlpha);
    
    fragColor = vec4(color, alpha);
}
