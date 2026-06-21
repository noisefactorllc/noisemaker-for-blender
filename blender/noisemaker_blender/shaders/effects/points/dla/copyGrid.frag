#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
// Copy Pass - Blit grid to write nm_buffer for proper blending

void main() {
    vec2 uv = gl_FragCoord.xy / resolution;
    fragColor = nmTex(gridTex, uv);
}
