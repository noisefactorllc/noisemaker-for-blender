#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
void main() {
    ivec2 coord = ivec2(gl_FragCoord.xy);
    vec4 base = texelFetch(inputTex, coord, 0);
    vec4 overlay = texelFetch(overlayTex, coord, 0);

    // Scratches use max-blend: bright white lines over image
    float scratchStrength = overlay.a * alpha;
    vec3 result = max(base.rgb, vec3(scratchStrength));
    fragColor = vec4(result, base.a);
}
