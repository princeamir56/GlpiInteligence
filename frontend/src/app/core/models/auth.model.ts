export type Role = 'DSI' | 'MANAGER' | 'DIRECTION';

export interface LoginRequest {
  username: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  role: Role;
  token_type?: string;
}

export interface CurrentUser {
  username: string;
  full_name?: string;
  role: Role;
  email?: string;
}
