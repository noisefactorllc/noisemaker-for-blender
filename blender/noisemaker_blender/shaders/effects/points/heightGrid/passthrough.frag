#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
void main() {
    vec2 uv = gl_FragCoord.xy / resolution;
    fragColor = nmTex(inputTex, uv);
}
