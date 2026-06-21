#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
// Passthrough shader - copy input to output for 2D chain continuity

void main() {
    ivec2 coord = ivec2(gl_FragCoord.xy);
    fragColor = texelFetch(inputTex, coord, 0);
}
