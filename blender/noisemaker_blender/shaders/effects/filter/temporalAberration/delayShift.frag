#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
/*
 * Temporal Chromatic Aberration - shift pass (one stage of the delay line).
 *
 * Copies the source stage into the destination stage, advancing the bucket-brigade shift
 * register by one frame. Alpha is preserved unchanged so the "filled" frontier (alpha 1
 * from the live input vs. alpha 0 from never-written stages) propagates exactly one stage
 * per frame, which the read pass uses for its ramp-in fallback.
 */

void main() {
    ivec2 texSize = textureSize(srcTex, 0);
    vec2 uv = gl_FragCoord.xy / vec2(texSize);
    fragColor = nmTex(srcTex, uv);
}
