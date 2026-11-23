#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
void main() {
    ivec2 coord = ivec2(gl_FragCoord.xy);
    ivec2 stateSize = textureSize(xyzTex, 0);
    // pointsEmit allocates a square state texture: one grid nm_vertex per slot.
    vec2 uv = (vec2(coord) + 0.5) / vec2(stateSize);
    vec3 heightColor = nmTex(heightTex, uv).rgb;
    float elevation = dot(heightColor, vec3(0.2126, 0.7152, 0.0722));
    // The grid is gridScale wide, and as deep as the frame's shape makes it.
    // Every surface has the frame's shape, so what is drawn on the grid keeps
    // its proportions. aspectInv is the frame's height over its width. It is
    // computed outside the shader, so both backends multiply by one value,
    // and on a square frame it is exactly 1.
    float gridDepth = gridScale * aspectInv;
    // XZ ground plane, Y elevation. These are world coordinates, not UVs.
    // The image's top row lies at -Z, so a view from above along -Y with
    // screen right on +X shows the image as authored, not mirrored.
    outXYZ = vec4((uv.x - 0.5) * gridScale,
        elevation * heightScale + heightOffset,
        (0.5 - uv.y) * gridDepth, 1.0);
    outVel = vec4(0.0, 0.0, 0.0, texelFetch(velTex, coord, 0).w);
    outRGBA = nmTex(diffuseTex, uv);
}
