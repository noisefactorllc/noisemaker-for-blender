#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
void main() {
    ivec2 coord = ivec2(gl_FragCoord.xy);
    ivec2 stateSize = textureSize(xyzTex, 0);
    // pointsEmit allocates a square state texture: one grid nm_vertex per slot.
    vec2 uv = (vec2(coord) + 0.5) / vec2(stateSize);
    vec3 heightColor = nmTex(heightTex, uv).rgb;
    float elevation = dot(heightColor, vec3(0.2126, 0.7152, 0.0722));
    // XZ ground plane, Y elevation. These are world coordinates, not UVs.
    outXYZ = vec4((uv.x - 0.5) * gridScale,
        elevation * heightScale + heightOffset,
        (uv.y - 0.5) * gridScale, 1.0);
    outVel = vec4(0.0, 0.0, 0.0, texelFetch(velTex, coord, 0).w);
    outRGBA = nmTex(diffuseTex, uv);
}
