#define nmTex(s, uv) (texelFetch((s), clamp(ivec2(floor((uv)*vec2(textureSize((s),0)))), ivec2(0), textureSize((s),0)-ivec2(1)), 0))
void main(){
  // Compute global UV from tile-local coordinates
  vec2 globalCoord = gl_FragCoord.xy + tileOffset;
  vec2 st = globalCoord / fullResolution;
  
  // Apply scale transform in global UV space (centered and aspect-corrected)
  vec2 c = vec2(-centerX, centerY);
  st -= c;
  st.x *= aspect;
  st = st / vec2(scaleX, scaleY);
  st.x /= aspect;
  st += c;
  
  // Convert global UV to local UV for sampling inputTex
  vec2 localUV = (st * fullResolution - tileOffset) / resolution;
  
  // Apply wrap mode to local UV
  if (wrap == 0) {
      // mirror
      localUV = abs(mod(localUV + 1.0, 2.0) - 1.0);
  } else if (wrap == 1) {
      // repeat
      localUV = fract(localUV);
  } else {
      // clamp
      localUV = clamp(localUV, 0.0, 1.0);
  }
  
  fragColor = vec4(nmTex(inputTex, localUV).rgb, 1.0);
}
